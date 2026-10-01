#!/usr/bin/env python3
"""Resolve where SupraMAS keeps its assets, and where a run writes its output.

Two roots, deliberately separate:

* **Asset root** — the SupraMAS installation: `tools/`, `schemas/`, the role
  contracts under `agents/`, and the bundle patch. Read-only. Its layout differs
  between a source checkout and an installed bundle:

  ```text
  source checkout                    installed bundle
  <repo>/                            <bundle>/
  ├── tools/                         ├── assets/
  ├── schemas/                       │   ├── tools/
  ├── packages/supramas-dsh/         │   ├── schemas/
  │   ├── agents/                    │   └── scripts/   <- this file
  │   ├── cordis.patch.yml           ├── agents/
  │   └── presets/                   ├── cordis.patch.yml
  └── scripts/                       └── presets/
  ```

* **Workspace** — the caller's project. `runs/{job_id}/` is written here, and the
  agent's file tools are scoped to it. Defaults to the current directory.

In a source checkout the two happen to coincide with the repository root, which
is why they used to be a single constant. An installed bundle lives inside a
profile's `node_modules/`, so writing runs next to it would be wrong.

Every value is overridable from the command line (`--asset-root`,
`--workspace`) and from the environment (`SUPRAMAS_ASSET_ROOT`,
`SUPRAMAS_WORKSPACE`), so a caller can pin either explicitly.
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

ENV_ASSET_ROOT = "SUPRAMAS_ASSET_ROOT"
ENV_WORKSPACE = "SUPRAMAS_WORKSPACE"

_AGENTS_MARKER = "strategy-builder-agent.md"
_PATCH_NAME = "cordis.patch.yml"


class AssetRootNotFound(RuntimeError):
    """Raised when no directory looks like a SupraMAS installation."""


def _looks_like_assets(path: Path) -> bool:
    return (path / "tools").is_dir() and (path / "schemas").is_dir()


def _candidates() -> list[Path]:
    """Directories that could be the asset root, most specific first.

    `HERE` is `<repo>/scripts` in a checkout and `<bundle>/assets/scripts` in an
    installed bundle, so the two layouts need different parents.
    """
    bundle_maybe = HERE.parent.parent
    asset_maybe = HERE.parent
    return [
        asset_maybe,                                   # bundle: <bundle>/assets/
        asset_maybe.parent,                            # checkout: <repo>/
        bundle_maybe,                                  # defensive: <bundle>/
    ]


def asset_root() -> Path:
    """Directory holding `tools/` and `schemas/`."""
    override = os.environ.get(ENV_ASSET_ROOT)
    if override:
        path = Path(override).expanduser().resolve()
        if not _looks_like_assets(path):
            raise AssetRootNotFound(
                f"{ENV_ASSET_ROOT}={override} does not contain tools/ and schemas/"
            )
        return path
    for candidate in _candidates():
        if _looks_like_assets(candidate):
            return candidate
    raise AssetRootNotFound(
        "cannot locate the SupraMAS asset root (a directory containing tools/ and "
        f"schemas/); looked in: {', '.join(str(c) for c in _candidates())}. "
        f"Set {ENV_ASSET_ROOT} to override."
    )


def agents_dir() -> Path:
    """Directory holding the role contracts."""
    for candidate in (
        asset_root() / "packages" / "supramas-dsh" / "agents",   # checkout
        asset_root().parent / "agents",                          # installed bundle
        asset_root() / "agents",
    ):
        if (candidate / _AGENTS_MARKER).is_file():
            return candidate
    raise AssetRootNotFound(f"cannot locate the role contracts ({_AGENTS_MARKER})")


def bundle_patch() -> Path:
    """The profile-level bundle patch registering the delegation roles."""
    for candidate in (
        asset_root() / "packages" / "supramas-dsh" / _PATCH_NAME,   # checkout
        asset_root().parent / _PATCH_NAME,                          # installed bundle
        asset_root() / _PATCH_NAME,
    ):
        if candidate.is_file():
            return candidate
    raise AssetRootNotFound(f"cannot locate {_PATCH_NAME}")


def skills_dir() -> Path | None:
    """The authored skill tree, when it is present (checkout and bundle both ship it)."""
    for candidate in (asset_root() / "skills", asset_root() / "assets" / "skills"):
        if candidate.is_dir():
            return candidate
    return None


def tools_dir() -> Path:
    return asset_root() / "tools"


def schemas_dir() -> Path:
    return asset_root() / "schemas"


def workspace() -> Path:
    """Where `runs/` is written. Defaults to the current directory."""
    override = os.environ.get(ENV_WORKSPACE)
    return Path(override).expanduser().resolve() if override else Path.cwd().resolve()


def schema_path(name: str) -> Path:
    """Resolve a schema by file name against the asset root."""
    path = schemas_dir() / name
    if not path.is_file():
        raise AssetRootNotFound(f"schema not found: {path}")
    return path


def tool_path(name: str) -> Path:
    """Resolve a bundled Python helper by file name against the asset root."""
    path = tools_dir() / name
    if not path.is_file():
        raise AssetRootNotFound(f"helper not found: {path}")
    return path


def describe() -> dict[str, str]:
    """Everything a `--self-check` needs to print."""
    skills = skills_dir()
    return {
        "asset_root": str(asset_root()),
        "agents_dir": str(agents_dir()),
        "bundle_patch": str(bundle_patch()),
        "tools_dir": str(tools_dir()),
        "schemas_dir": str(schemas_dir()),
        "skills_dir": str(skills) if skills else "(not present)",
        "workspace": str(workspace()),
    }


if __name__ == "__main__":
    for key, value in describe().items():
        print(f"{key:14s} {value}")
