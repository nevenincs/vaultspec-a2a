#!/usr/bin/env bash
set -euo pipefail
case "$TARGET" in
  *windows*) bin="dist/binary/vaultspec-a2a/vaultspec-a2a.exe" ;;
  *)         bin="dist/binary/vaultspec-a2a/vaultspec-a2a" ;;
esac
test -x "$bin" || { echo "::error::frozen binary absent or not executable at $bin" >&2; exit 1; }
# NOT under RUNNER_TEMP. That directory is the runner agent's own
# scratch and is written to continuously while a job runs, which on
# Windows puts a third party on files microseconds after this process
# creates them. Publishing the discovery credential renames a file it
# has just written, and a rename is a delete-class operation on its
# source: any other opener holding it without DELETE sharing denies
# the publish. A private directory under the workspace has no such
# traffic. (Two openers that caused this were ours and are fixed; this
# removes the remaining environmental one.)
home="${GITHUB_WORKSPACE}/.a2a-smoke-home"
rm -rf "$home"
mkdir -p "$home"

echo "--- setup (local only; provisions the home and runs bundled migrations)"
"$bin" setup --app-home "$home"

# `--log` captures the SPAWNED gateway's own stdout/stderr. Without it a
# startup failure reports only the child's exit code, and the CLI's own
# error says so: "start with --log to capture output". An exit code with
# no output is not a diagnosis — it names that something failed without
# naming what, which is the failure class this gate exists to close.
gwlog="${GITHUB_WORKSPACE}/.a2a-smoke-gateway.log"
echo "--- start (blocks until discoverably healthy, emits ServiceStatus)"
if ! "$bin" start --app-home "$home" --host 127.0.0.1 --port "${SMOKE_PORT}" --log "$gwlog" > start.json; then
  echo "::error::start failed; the spawned gateway's own output follows" >&2
  echo "===== gateway log ($gwlog) ====="
  cat "$gwlog" 2>/dev/null || echo "(no gateway log was produced)"
  echo "===== end gateway log ====="
  echo "===== app home after the failed start ====="
  find "$home" -maxdepth 2 2>/dev/null | sed "s|^$home|<app-home>|" | sort || true

  # Who else is holding the home. A startup failure here has twice been
  # a Windows sharing violation on a file the gateway had just created
  # itself, and the one thing the traceback cannot say is which other
  # process was holding it. Naming the live vaultspec-a2a processes
  # costs nothing and is the missing half of that diagnosis.
  echo "===== other vaultspec-a2a processes at the time of failure ====="
  if [ "${RUNNER_OS}" = "Windows" ]; then
    tasklist //FI "IMAGENAME eq vaultspec-a2a.exe" 2>/dev/null || true
  else
    # pgrep rather than grepping ps: it matches processes directly, so
    # there is no self-match to dodge and no dependence on this shell's
    # ps column layout.
    pgrep -af vaultspec-a2a || echo "(none)"
  fi
  exit 1
fi
cat start.json
read -r state healthy pid base <<EOF
$($PY -c 'import json;d=json.load(open("start.json"));print(d["state"],d["healthy"],d["pid"],d["base_url"])')
EOF
echo "state=$state healthy=$healthy pid=$pid base=$base"
[ "$state" = "running" ] || { echo "::error::start reported state '$state', expected 'running'" >&2; exit 1; }
[ "$healthy" = "True" ] || { echo "::error::start reported healthy='$healthy'" >&2; exit 1; }
case "$pid" in ''|None|0) echo "::error::start reported no pid" >&2; exit 1 ;; esac

echo "--- status must exit 0 while the gateway is running"
"$bin" status --app-home "$home"

# What the running gateway actually publishes into its app home, by
# NAME only. This is the discovery handshake a consumer has to find,
# and reading it off a live run is better evidence than reading it off
# the source. Names only, never contents: this directory holds an
# owner-restricted bearer token.
echo "--- discovery surface published into the app home"
find "$home" -maxdepth 2 -type f | sed "s|^$home|<app-home>|" | sort

echo "--- USE THE API: /health must answer 200 AND report ready"
ok=""
for _ in $(seq 1 30); do
  if curl -fsS -o health.json "$base/health" 2>/dev/null; then ok=yes; break; fi
  sleep 2
done
[ -n "$ok" ] || { echo "::error::/health never answered at $base within 60s" >&2; exit 1; }
cat health.json
# 200 alone is not readiness: this endpoint answers 200 while `ready`
# is false (for example with the worker down), so assert the field.
#
# `ready` is the field, and ONLY that field. The composite `status`
# reports `degraded` on a cold gateway because no worker is spawned yet
# — which is the designed behaviour, not a fault: demand attaches to a
# worker on first use and nothing starts eagerly. Requiring
# `status == "ok"` here demanded an eagerly-spawned worker the product
# deliberately does not create, and failed all four targets on a gateway
# that had just reported itself ready.
"$PY" -c '
import json,sys
d=json.load(open("health.json"))
if d.get("ready") is not True:
    sys.exit(f"/health answered but is not ready: {d}")
print("health ready (composite status=" + str(d.get("status")) + ")")'

echo "--- stop"
"$bin" stop --app-home "$home"

echo "--- status must now exit non-zero (gateway stopped)"
if "$bin" status --app-home "$home"; then
  echo "::error::status exited 0 after stop; the gateway is still resident" >&2
  exit 1
fi

echo "--- and the process must actually be gone, not merely reported stopped"
if [ "${RUNNER_OS}" = "Windows" ]; then
  if tasklist //FI "PID eq ${pid}" 2>/dev/null | grep -q "${pid}"; then
    echo "::error::pid ${pid} is still alive after stop" >&2; exit 1
  fi
elif kill -0 "${pid}" 2>/dev/null; then
  echo "::error::pid ${pid} is still alive after stop" >&2; exit 1
fi
echo "lifecycle smoke OK: started, served /health, stopped, pid reaped"
