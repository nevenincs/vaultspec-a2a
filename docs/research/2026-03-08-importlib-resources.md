# importlib.resources for Non-Python Asset Resolution — 2026-03-08

## Problem Statement (DCK-L09 + APP-N04 + PROV-O02)

Two path resolution patterns in the codebase use fragile `__file__` parent
traversal that breaks in non-editable (pip/uv) installs:

1. **`api/app.py` line 71-74 (`_UI_BUILD_DIR`):**
   ```python
   Path(__file__).resolve().parent.parent.parent.parent / "src" / "ui" / "dist"
   # Expects: project_root/src/ui/dist
   # In non-editable: site-packages/vaultspec_a2a/api/app.py
   #   -> traverses to site-packages/../../../ -> WRONG
   ```

2. **`providers/factory.py` line 28-32 (`_PROJECT_ROOT`):**
   ```python
   Path(__file__).resolve().parent.parent.parent.parent
   # Expects: project_root (to find node_modules/)
   # In non-editable: site-packages/vaultspec_a2a/providers/factory.py
   #   -> traverses to site-packages/../../../ -> WRONG
   ```

Both have environment variable overrides (`VAULTSPEC_UI_BUILD_DIR`,
`VAULTSPEC_PROJECT_ROOT`) that work in Docker. The question is whether there's
a more robust approach using Python's packaging APIs.

---

## 1. Core Distinction: Package Data vs External Assets

### 1.1 Package Data (importlib.resources can find these)

Files that are **part of the Python package** and shipped inside the package
directory. Examples: templates, default configs, SQL migration scripts.

```
vaultspec_a2a/
  database/
    migrations/          # Package data: inside the package
      versions/
        001_initial.py
  core/
    presets/              # Package data: inside the package
      default.yaml
```

These are locatable via `importlib.resources.files("vaultspec_a2a")`.

### 1.2 External Assets (importlib.resources CANNOT find these)

Files that are **outside the Python package** directory:
- `src/ui/dist/` -- React SPA build output (JavaScript, CSS, HTML)
- `node_modules/` -- Node.js dependencies for ACP runtime

These are NOT part of `vaultspec_a2a` the Python package. They exist at the
project root level, not inside `src/vaultspec_a2a/`.

**importlib.resources is fundamentally incapable of locating external assets.**
It can only traverse the package tree rooted at the package's `__init__.py`.

---

## 2. importlib.resources API (Python 3.13)

### 2.1 `importlib.resources.files()` — Primary API

```python
import importlib.resources

# Returns a Traversable pointing to the package root directory
ref = importlib.resources.files("vaultspec_a2a")
# In editable install: Y:\code\...\src\vaultspec_a2a (source tree)
# In non-editable:     .venv/Lib/site-packages/vaultspec_a2a

# Navigate within the package
migrations = ref / "database" / "migrations"
presets = ref / "core" / "presets"
```

**Verified on Python 3.13 (Windows 11):**
```python
>>> importlib.resources.files("vaultspec_a2a")
WindowsPath('Y:\\code\\...\\src\\vaultspec_a2a')
# Returns a real Path object (not an abstract Traversable)
```

### 2.2 `importlib.resources.as_file()` — Context Manager

For resources that may be in a zip (egg) or other non-filesystem location,
`as_file()` extracts to a temporary file:

```python
ref = importlib.resources.files("vaultspec_a2a") / "core" / "presets" / "default.yaml"
with importlib.resources.as_file(ref) as path:
    # path is a real filesystem Path, even if the package is in a zip
    config = yaml.safe_load(path.read_text())
```

Not needed for our case -- `uv sync --no-editable` installs to a real
filesystem directory, not a zip.

### 2.3 Editable vs Non-Editable Behavior

| Install Mode | `files()` returns | `__file__` traversal |
|-------------|------------------|---------------------|
| Editable (`uv sync`) | Source tree path (via `.pth` file) | Works (source tree is project root child) |
| Non-editable (`uv sync --no-editable`) | site-packages path | **BROKEN** (site-packages is not project root) |
| Docker prod (`uv sync --no-editable --frozen`) | site-packages path | **BROKEN** |

**Verified:** Our current dev setup uses editable install. The `.pth` file at
`site-packages/_vaultspec_a2a.pth` contains the source tree path. This is why
`__file__` traversal works in development but breaks in Docker.

---

## 3. importlib.metadata for Package Installation Root

### 3.1 `importlib.metadata.distribution()` — Package Metadata

```python
import importlib.metadata

d = importlib.metadata.distribution("vaultspec-a2a")
# d._path = .venv/Lib/site-packages/vaultspec_a2a-0.1.0.dist-info
# d._path.parent = .venv/Lib/site-packages/
```

**This only gives you site-packages**, not the project root. In a non-editable
install, there is no connection between site-packages and the original source
tree. The package is a copy.

### 3.2 `d.files` — Package File List

```python
d = importlib.metadata.distribution("vaultspec-a2a")
for f in d.files:
    print(f)
# ../../Scripts/vaultspec-mcp.exe
# ../../Scripts/vaultspec.exe
# _vaultspec_a2a.pth
# vaultspec_a2a-0.1.0.dist-info/INSTALLER
# ...
```

Paths are relative to the dist-info directory. This can locate installed
package files but NOT external assets.

---

## 4. Patterns for Locating External Assets

Since importlib.resources cannot find assets outside the package, we need
alternative strategies.

### 4.1 Pattern A: Environment Variable Override — CURRENT (Correct)

```python
_UI_BUILD_DIR = (
    Path(os.environ["VAULTSPEC_UI_BUILD_DIR"])
    if "VAULTSPEC_UI_BUILD_DIR" in os.environ
    else Path(__file__).resolve().parent.parent.parent.parent / "src" / "ui" / "dist"
)
```

**Evaluation:**
- Works in Docker: env var set in Dockerfile
- Works in dev: `__file__` traversal works in editable installs
- **The fallback is fragile** -- breaks in non-editable installs without env var
- Cross-platform: env vars work identically on Windows/Linux/macOS

### 4.2 Pattern B: Include Assets as Package Data

Move or copy external assets INTO the Python package so `importlib.resources`
can find them.

```toml
# pyproject.toml
[tool.setuptools.package-data]
"vaultspec_a2a" = ["ui_dist/**/*"]
```

Then in code:
```python
ui_dist = importlib.resources.files("vaultspec_a2a") / "ui_dist"
```

**Problem for SPA assets:**
- The UI build (`npm run build`) outputs to `src/ui/dist/`
- To include in the Python package, you'd need to copy these files to
  `src/vaultspec_a2a/ui_dist/` before `uv sync`
- This adds a build step coupling and ~2MB of JS/CSS to the Python package
- In Docker, the `COPY --from=frontend-build` already handles this correctly

**Problem for node_modules:**
- node_modules is 84-170MB. Including it in the Python package is not viable.
- It's a Node.js ecosystem artifact, not Python package data.

**Verdict:** Not practical for SPA assets or node_modules.

### 4.3 Pattern C: pkg_resources / importlib with Data Directory

Define a data directory in the package and use it as the root for external
asset references:

```python
# In __init__.py or a dedicated paths module:
import importlib.resources

_PACKAGE_ROOT = importlib.resources.files("vaultspec_a2a")

# For assets that are part of the package:
MIGRATIONS_DIR = _PACKAGE_ROOT / "database" / "migrations"
PRESETS_DIR = _PACKAGE_ROOT / "core" / "presets"

# For external assets: env var with package-relative fallback
UI_BUILD_DIR = (
    Path(os.environ["VAULTSPEC_UI_BUILD_DIR"])
    if "VAULTSPEC_UI_BUILD_DIR" in os.environ
    else _PACKAGE_ROOT.parent.parent / "ui" / "dist"  # src/ui/dist relative to src/vaultspec_a2a
)
```

**Problem:** The `_PACKAGE_ROOT.parent.parent` traversal has the same issue as
`__file__` traversal in non-editable installs. `_PACKAGE_ROOT` points to
site-packages, so `.parent.parent` goes to the wrong place.

### 4.4 Pattern D: Centralized Path Resolution Module — RECOMMENDED

Create a single module that resolves all paths with clear fallback chain:

```python
# src/vaultspec_a2a/paths.py
"""Centralized path resolution for all non-Python assets.

Resolution order:
1. Environment variable (always wins -- Docker, CI, custom deployments)
2. importlib.resources for package-internal assets
3. __file__ traversal for editable-install dev mode (ONLY when env var absent)

Cross-platform: uses pathlib.Path throughout. Env vars work identically on
Windows, Linux, macOS.
"""
import importlib.resources
import os
from pathlib import Path

_PACKAGE_ROOT = Path(str(importlib.resources.files("vaultspec_a2a")))

def _dev_project_root() -> Path | None:
    """Attempt to locate the project root via __file__ traversal.

    Only valid in editable installs where __file__ is in the source tree.
    Returns None if the traversed path doesn't look like a project root.
    """
    candidate = _PACKAGE_ROOT.parent.parent  # src/ -> project root
    if (candidate / "pyproject.toml").is_file():
        return candidate
    return None

def resolve_ui_build_dir() -> Path | None:
    """Resolve the React SPA build directory."""
    if env := os.environ.get("VAULTSPEC_UI_BUILD_DIR"):
        return Path(env)
    if root := _dev_project_root():
        return root / "src" / "ui" / "dist"
    return None

def resolve_project_root() -> Path | None:
    """Resolve the project root (for node_modules, etc.)."""
    if env := os.environ.get("VAULTSPEC_PROJECT_ROOT"):
        return Path(env)
    return _dev_project_root()

def resolve_acp_entry_point() -> Path | None:
    """Resolve the ACP JavaScript entry point."""
    root = resolve_project_root()
    if root is None:
        return None
    candidate = (
        root / "node_modules" / "@zed-industries"
        / "claude-agent-acp" / "dist" / "index.js"
    )
    return candidate if candidate.is_file() else None
```

**Validation guard:** The `_dev_project_root()` function checks for
`pyproject.toml` at the traversed path. If absent (non-editable install without
env var), it returns `None` instead of a garbage path.

**Benefits:**
- Single source of truth for all path resolution
- Clear priority: env var > importlib > __file__ with validation
- `None` return signals "asset not available" (instead of a wrong path)
- Callers can provide actionable errors: "Set VAULTSPEC_UI_BUILD_DIR"
- Cross-platform: `Path` and `os.environ` are identical on all platforms

---

## 5. What importlib.resources IS Good For

Even though it can't solve the external asset problem, there are legitimate
uses within the package:

### 5.1 Alembic Migration Scripts

```python
# Instead of:
_MIGRATIONS = Path(__file__).parent / "migrations"

# Use:
_MIGRATIONS = importlib.resources.files("vaultspec_a2a") / "database" / "migrations"
```

This works in both editable and non-editable installs because migrations are
inside the package.

### 5.2 Team Preset YAML Files

```python
# Instead of:
_PRESETS_DIR = Path(__file__).parent / "presets"

# Use:
_PRESETS_DIR = importlib.resources.files("vaultspec_a2a") / "core" / "presets"
```

### 5.3 Rules Discovery

```python
# Rules are in .vaultspec/rules/ which is project-level, not package-level
# importlib.resources does NOT help here
# Use workspace_root from settings instead
```

---

## 6. Recommendation

### 6.1 Keep Environment Variable Overrides (Immediate Fix)

The current approach with `VAULTSPEC_UI_BUILD_DIR` and `VAULTSPEC_PROJECT_ROOT`
is correct for Docker and CI. The Docker prod.Dockerfile already sets both.

### 6.2 Add Validation Guard (Short Term)

Replace blind `__file__` traversal with the validated pattern from Section 4.4.
When the traversed path doesn't contain `pyproject.toml`, return `None` and
raise a descriptive `ConfigError` at the call site.

### 6.3 Centralize in `paths.py` (Medium Term)

Create `src/vaultspec_a2a/paths.py` as shown in Pattern D. All path-sensitive
code imports from there. Benefits:
- Single file to audit for path correctness
- Clear env var documentation in one place
- Easy to test (mock env vars, check resolved paths)

### 6.4 Use importlib.resources for Package-Internal Assets (Low Priority)

Migrate internal asset paths (migrations, presets) from `__file__` to
`importlib.resources.files()`. This is a low-priority cleanup since these
paths work correctly today (they're inside the package, not external).

### 6.5 Cross-Platform Notes

- `importlib.resources.files()` returns `WindowsPath` on Windows, `PosixPath`
  on Linux/macOS. Both are `pathlib.Path` subclasses -- no platform branching
  needed.
- Environment variables (`os.environ.get()`) work identically on all platforms.
- `pathlib.Path` handles path separators correctly on all platforms.
- No platform-specific code needed for any of these patterns.
