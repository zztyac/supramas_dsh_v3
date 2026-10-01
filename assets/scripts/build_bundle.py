#!/usr/bin/env python3
"""Stage the runtime assets a published SupraMAS bundle needs.

The source of truth stays at the repository root (`skills/`, `tools/`,
`schemas/`). Publishing copies them into `packages/supramas-dsh/assets/` so the
bundle is self-contained: a remote user who runs
`dsh plugin add git+https://.../supramas_dsh_v3.git` gets the skills, helpers, and
schemas without cloning this repo.

`lib/index.js` registers `assets/skills/` with the harness and appends the
absolute `assets/tools/` and `assets/schemas/` paths to every skill body, so the
copies are what a remote session actually reads.

Usage:
    python3 scripts/build_bundle.py            # copy
    python3 scripts/build_bundle.py --check    # verify the copies are current
    python3 scripts/build_bundle.py --clean    # remove the staged assets
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = REPO_ROOT / "packages" / "supramas-dsh"
ASSETS_DIR = BUNDLE_DIR / "assets"

# source directory -> destination directory under assets/
#
# `scripts/` ships too: without the orchestration layer a remote user gets the
# skills and role tools but cannot run the deterministic pipeline. It resolves
# its own assets through `supramas_paths`, which is why the bundle layout
# (`assets/scripts/`) works without any rewriting.
STAGED = {
    REPO_ROOT / "skills": ASSETS_DIR / "skills",
    REPO_ROOT / "tools": ASSETS_DIR / "tools",
    REPO_ROOT / "schemas": ASSETS_DIR / "schemas",
    REPO_ROOT / "scripts": ASSETS_DIR / "scripts",
}

# Single files copied beside the assets rather than under a directory.
STAGED_FILES = {
    REPO_ROOT / "AGENTS.md": ASSETS_DIR / "AGENTS.md",
}

# Only these reach a published bundle; keep sandbox noise and caches out.
INCLUDE_SUFFIXES = {".md", ".py", ".json"}
EXCLUDE_DIRS = {"__pycache__", "raw", "tests"}


def source_files(source: Path):
    for path in sorted(source.rglob("*")):
        if path.is_dir() or any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix in INCLUDE_SUFFIXES:
            yield path


def plan() -> list[tuple[Path, Path]]:
    """Return (source, destination) pairs for every staged file."""
    pairs: list[tuple[Path, Path]] = []
    for source_root, dest_root in STAGED.items():
        if not source_root.is_dir():
            raise SystemExit(f"missing source directory: {source_root}")
        for path in source_files(source_root):
            pairs.append((path, dest_root / path.relative_to(source_root)))
    for source, destination in STAGED_FILES.items():
        if not source.is_file():
            raise SystemExit(f"missing source file: {source}")
        pairs.append((source, destination))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify instead of copying.")
    parser.add_argument("--clean", action="store_true", help="Remove the staged assets.")
    args = parser.parse_args()

    if args.clean:
        shutil.rmtree(ASSETS_DIR, ignore_errors=True)
        print(f"removed {ASSETS_DIR}")
        return 0

    pairs = plan()

    if args.check:
        stale: list[str] = []
        for source, destination in pairs:
            if not destination.is_file() or not filecmp.cmp(source, destination, shallow=False):
                stale.append(str(destination.relative_to(REPO_ROOT)))
        # Files staged earlier but no longer produced are also stale.
        expected = {destination for _source, destination in pairs}
        for path in sorted(ASSETS_DIR.rglob("*")) if ASSETS_DIR.is_dir() else []:
            if path.is_file() and path not in expected:
                stale.append(f"{path.relative_to(REPO_ROOT)} (orphan)")
        if stale:
            print("staged assets are out of date:", file=sys.stderr)
            for entry in stale[:20]:
                print(f"  {entry}", file=sys.stderr)
            print("run scripts/build_bundle.py", file=sys.stderr)
            return 1
        print(f"up to date: {len(pairs)} staged files")
        return 0

    # Rebuild from scratch so removed sources do not linger.
    shutil.rmtree(ASSETS_DIR, ignore_errors=True)
    for source, destination in pairs:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    counts: dict[str, int] = {}
    for _source, destination in pairs:
        key = destination.relative_to(ASSETS_DIR).parts[0]
        counts[key] = counts.get(key, 0) + 1
    summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
    print(f"staged {len(pairs)} files into {ASSETS_DIR.relative_to(REPO_ROOT)} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
