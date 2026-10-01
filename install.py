#!/usr/bin/env python3
"""Install supramas-dsh into a DeepSeek Harness profile, and register it as a bundle.

**Normally you do not need this.** `dsh plugin --profile <p> add <source>`
registers a public (non-`private`) package under `dsh.profile.bundles` by itself,
so the whole install is:

    dsh plugin --profile desktop add git+ssh://git@github.com/zztyac/supramas_dsh_v3.git

Use this script when that did not happen — most often because the package was
installed while it still declared `"private": true`, which suppresses the
automatic registration:

    python3 <installed-package>/install.py --profile desktop     # install + register
    python3 <installed-package>/install.py --profile desktop --register-only

It is idempotent, reports what it would change under `--dry-run`, and backs up the
profile manifest before writing. Delegate to `dsh plugin add` for the pnpm step so
the profile's own lockfile and store stay authoritative.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# The name the bundle registers under, i.e. the `name` in its package.json.
PACKAGE_NAME = "supramas-dsh"

# Where to fetch it from by default. The git URL, not the bare package name:
# this bundle is distributed from a repository, so `pnpm add supramas-dsh` would
# look for an unrelated npm package.
DEFAULT_SOURCE = "git+ssh://git@github.com/zztyac/supramas_dsh_v3.git"


def dsh_home() -> Path:
    return Path(os.environ.get("DSH_HOME", Path.home() / ".dsh")).expanduser()


def profiles_root() -> Path:
    return dsh_home() / "profiles"


def list_profiles() -> list[str]:
    root = profiles_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "package.json").is_file())


def detect_profile() -> str:
    """Pick a profile when none was named: prefer `desktop` (the GUI), else the only one."""
    names = list_profiles()
    if not names:
        raise SystemExit(
            f"no DeepSeek Harness profiles under {profiles_root()}; pass --profile"
        )
    if "desktop" in names:
        return "desktop"
    if len(names) == 1:
        return names[0]
    raise SystemExit(
        f"several profiles exist ({', '.join(names)}); pass --profile to choose one"
    )


def find_dsh() -> str | None:
    override = os.environ.get("DSH_BIN")
    if override:
        return override
    found = shutil.which("dsh")
    if found:
        return found
    macos = Path(
        "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"
    )
    return str(macos) if macos.is_file() else None


def install_package(profile: str, source: str) -> bool:
    """Run `dsh plugin --profile <profile> add <source>` if the CLI is available."""
    launcher = find_dsh()
    if not launcher:
        return False
    print(f"installing {source}\n  into profile {profile} ...")
    completed = subprocess.run(
        [launcher, "plugin", "--profile", profile, "add", source],
        text=True,
        check=False,
    )
    return completed.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="Profile to register into. Defaults to desktop.")
    parser.add_argument(
        "--from",
        dest="source",
        default=DEFAULT_SOURCE,
        help=f"Install source passed to `dsh plugin add` (default: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "--register-only",
        action="store_true",
        help="Skip `dsh plugin add`; only edit the profile manifest.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change, write nothing."
    )
    args = parser.parse_args()

    profile = args.profile or detect_profile()
    profile_dir = profiles_root() / profile
    manifest_path = profile_dir / "package.json"
    if not manifest_path.is_file():
        raise SystemExit(f"profile manifest not found: {manifest_path}")

    # Install first: registering a bundle that is not on disk silently does nothing.
    if not args.register_only:
        if not install_package(profile, args.source):
            installed = (profile_dir / "node_modules" / PACKAGE_NAME).is_dir()
            if not installed:
                print(
                    f"could not install {args.source}. Install it manually, then re-run "
                    f"with --register-only:\n"
                    f"  dsh plugin --profile {profile} add {args.source}",
                    file=sys.stderr,
                )
                return 1

    package_dir = profile_dir / "node_modules" / PACKAGE_NAME
    if not package_dir.is_dir():
        print(
            f"{PACKAGE_NAME} is not installed under {profile_dir / 'node_modules'}; "
            f"run `dsh plugin --profile {profile} add {args.source}` first",
            file=sys.stderr,
        )
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dsh_section = manifest.setdefault("dsh", {}).setdefault("profile", {})
    bundles = dsh_section.setdefault("bundles", [])
    dependencies = manifest.setdefault("dependencies", {})

    changes: list[str] = []
    if PACKAGE_NAME not in bundles:
        bundles.append(PACKAGE_NAME)
        changes.append(f"dsh.profile.bundles += {PACKAGE_NAME}")
    if PACKAGE_NAME not in dependencies:
        # pnpm normally records this; keep it explicit so a later `pnpm install`
        # does not prune the package.
        dependencies[PACKAGE_NAME] = f"file:{package_dir}"
        changes.append(f"dependencies.{PACKAGE_NAME} = file:{package_dir}")

    print(f"profile:  {profile}  ({manifest_path})")
    print(f"package:  {package_dir}")

    if not changes:
        print("already registered; nothing to do")
        return 0

    for change in changes:
        print(f"  + {change}")

    if args.dry_run:
        print("dry run: nothing written")
        return 0

    backup = manifest_path.with_suffix(
        f".json.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    shutil.copy2(manifest_path, backup)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"backup:   {backup}")
    print()
    print("registered. Next:")
    print("  - reload the DeepSeek Harness app (or start a new session)")
    print("  - the `材料学科研` preset appears under Settings -> General -> agent preset")
    print(f"  - roll back with: cp {backup} {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
