#!/bin/bash
# Provision a disposable cloud container (Claude Code on the web) so the
# repository's own `just` recipes, prek hooks, ruff, ty, and pytest run without
# manual setup. Wire it in as the cloud environment's setup script:
#
#   bash scripts/cloud_session_setup.sh --cloud
#
# Unlike `just init`, this installs host packages and a Node release and pins
# uv's interpreter in the shell profile, which is only acceptable on a machine
# that exists to be thrown away. It therefore does nothing unless it is told it
# is on one, by `--cloud` or by the harness's own CLAUDE_CODE_REMOTE=true.
# Idempotent: every step checks before it installs, and `just init-full` is
# stamp-guarded.
set -euo pipefail

if [ "${1:-}" != "--cloud" ] && [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  echo "cloud_session_setup: not a cloud container; pass --cloud to force" >&2
  exit 0
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."

LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"
export PATH="$LOCAL_BIN:$PATH"

log() { printf '[cloud-setup] %s\n' "$*" >&2; }

# just and prek are host tools the README expects on PATH; both publish wheels,
# so uv installs them without a separate package manager.
for pkg in rust-just:just prek:prek; do
  dist="${pkg%%:*}"
  exe="${pkg##*:}"
  if ! command -v "$exe" >/dev/null 2>&1; then
    log "installing $dist"
    uv tool install --quiet "$dist"
  fi
done

# fd and sd are the repository's discovery and refactor tools. Debian ships fd
# as `fdfind`. Advisory: nothing in the gates depends on them.
if ! command -v fd >/dev/null 2>&1 || ! command -v sd >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    log "installing fd-find and sd"
    { apt-get install -y -qq fd-find sd >/dev/null 2>&1 \
      || { apt-get update -qq >/dev/null 2>&1 \
        && apt-get install -y -qq fd-find sd >/dev/null 2>&1; }; } \
      || log "fd/sd unavailable; continuing"
  fi
  if command -v fdfind >/dev/null 2>&1 && ! command -v fd >/dev/null 2>&1; then
    ln -sf "$(command -v fdfind)" "$LOCAL_BIN/fd"
  fi
fi

# The Claude ACP adapter's engines field pins an exact Node release, which the
# base image does not ship. Fetch the official build and verify it against the
# release's SHASUMS256.txt before it goes anywhere near PATH.
node_version="$(tr -d '[:space:]' < .node-version)"
if [ "$(node --version 2>/dev/null || true)" != "v$node_version" ]; then
  node_root="/opt/node-v$node_version"
  if [ ! -x "$node_root/bin/node" ]; then
    log "installing Node.js $node_version"
    archive="node-v$node_version-linux-x64.tar.xz"
    scratch="$(mktemp -d)"
    curl -fsSL -o "$scratch/$archive" "https://nodejs.org/dist/v$node_version/$archive"
    curl -fsSL -o "$scratch/SHASUMS256.txt" "https://nodejs.org/dist/v$node_version/SHASUMS256.txt"
    (cd "$scratch" && grep " $archive\$" SHASUMS256.txt | sha256sum -c --quiet -)
    mkdir -p "$node_root"
    tar -xJf "$scratch/$archive" -C "$node_root" --strip-components=1
    rm -rf "$scratch"
  fi
  for exe in node npm npx corepack; do
    ln -sf "$node_root/bin/$exe" "$LOCAL_BIN/$exe"
  done
fi

# actionlint-py ships only an sdist whose build downloads the actionlint binary
# with urllib. Python 3.13 enables VERIFY_X509_STRICT, which rejects the egress
# proxy's CA, so the in-lock build fails. Building the same sdist once under an
# older system interpreter leaves a compatible wheel in uv's cache, which the
# locked sync then reuses - but only if the prebuild verified the lock's own
# sdist hash, since a hash-less cache entry is re-downloaded by `--locked`.
if ! uv run --no-sync actionlint --version >/dev/null 2>&1; then
  lock_entry="$(awk '/^name = "actionlint-py"$/,/^$/' uv.lock)"
  actionlint_version="$(printf '%s\n' "$lock_entry" | sed -n 's/^version = "\(.*\)"$/\1/p')"
  actionlint_hash="$(printf '%s\n' "$lock_entry" | sed -n 's/.*hash = "\(sha256:[0-9a-f]*\)".*/\1/p')"
  for candidate in python3.12 python3.11; do
    if interpreter="$(command -v "$candidate")"; then
      log "prebuilding actionlint-py $actionlint_version with $candidate"
      scratch="$(mktemp -d)"
      printf 'actionlint-py==%s --hash=%s\n' "$actionlint_version" "$actionlint_hash" \
        > "$scratch/requirements.txt"
      uv pip install --quiet --python "$interpreter" --require-hashes \
        --target "$scratch/target" -r "$scratch/requirements.txt" \
        || log "actionlint-py prebuild failed; init will report it"
      rm -rf "$scratch"
      break
    fi
  done
fi

# Harness MCP servers launch through `uvx`, which resolves its interpreter from
# the host default rather than this project's pin; on an image whose default is
# older than the pin, the servers are unresolvable and every test that composes
# them fails. Pin uv to the project's version for this and every later shell.
python_version="$(tr -d '[:space:]' < .python-version)"
export UV_PYTHON="$python_version"
for rc in "$HOME/.bashrc" "$HOME/.profile"; do
  if ! grep -qs '^export UV_PYTHON=' "$rc"; then
    printf 'export UV_PYTHON=%s\n' "$python_version" >> "$rc"
  fi
done

# The repository's own initializer: locked uv sync of the tooling, server, and
# composed dev profiles; npm ci of the pinned ACP runtime; Vaultspec enrollment;
# and the prek pre-commit hook.
log "running just init-full"
just init-full >&2
