#!/usr/bin/env python3
"""Lint (and optionally fix) SKILL.md frontmatter for DeepSeek Harness.

DeepSeek Harness discovers skills from `<root>/<name>/SKILL.md` or `<root>/<name>.md`
and parses the YAML frontmatter itself. A skill whose frontmatter is invalid is
dropped with a warning only: the model-visible catalogue simply never lists it, so
a broken skill is indistinguishable from a missing one. This linter makes that
failure loud.

Rules enforced (from `@deepseek-ai/dsh-skill-filesystem`):
  * `name` is required and must be kebab-case.
  * `description` is required and must be non-empty.
  * Recognised optional keys: whenToUse, metadata, disable-model-invocation,
    user-invocable.
  * `disable-model-invocation` and `user-invocable` accept YAML booleans plus the
    case-insensitive literals true/false, yes/no, on/off, 1/0. Anything else drops
    the whole skill.

Usage:
    PYTHONDONTWRITEBYTECODE=1 python3 scripts/dsh_skill_lint.py [paths...] [--fix]

`--fix` only removes keys that are known to belong to other agent runtimes and
have no DeepSeek Harness meaning; it never rewrites a value.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_KEYS = ("name", "description")
OPTIONAL_KEYS = ("whenToUse", "metadata", "disable-model-invocation", "user-invocable")
KNOWN_KEYS = set(REQUIRED_KEYS) | set(OPTIONAL_KEYS)

BOOLEAN_KEYS = ("disable-model-invocation", "user-invocable")

# Keys owned by other agent runtimes (Claude Code / Codex). DeepSeek Harness does
# not read them, and they are safe to delete.
FOREIGN_KEYS = ("argument-hint", "allowed-tools")

TRUTHY = {"true", "yes", "on", "1"}
FALSY = {"false", "no", "off", "0"}

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

DEFAULT_ROOTS = ("skills",)


def split_frontmatter(text: str) -> tuple[list[str], str] | None:
    """Return (frontmatter lines, body) or None when there is no frontmatter."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], "\n".join(lines[index + 1 :])
    return None


def parse_keys(frontmatter: list[str]) -> dict[str, str | None]:
    """Collect top-level scalar keys; nested list items are ignored."""
    keys: dict[str, str | None] = {}
    for line in frontmatter:
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        keys[key.strip()] = value.strip() or None
    return keys


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def lint_skill(path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, foreign keys present)."""
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read: {exc}"], []

    split = split_frontmatter(text)
    if split is None:
        return ["missing or unterminated YAML frontmatter"], []
    frontmatter, _ = split
    keys = parse_keys(frontmatter)

    name = keys.get("name")
    if not name:
        errors.append("missing required key: name")
    else:
        name = unquote(name)
        if not KEBAB_RE.match(name):
            errors.append(f"name must be kebab-case, got: {name!r}")
        if path.parent.name != name and path.name == "SKILL.md":
            errors.append(
                f"directory name {path.parent.name!r} does not match frontmatter name {name!r}"
            )

    description = keys.get("description")
    if not description or not unquote(description):
        errors.append("missing or empty required key: description")

    for key in BOOLEAN_KEYS:
        if key not in keys:
            continue
        value = keys[key]
        if value is None:
            errors.append(f"{key} has no value; expected a boolean")
            continue
        lowered = unquote(value).lower()
        if lowered not in TRUTHY | FALSY:
            errors.append(
                f"{key} must be a boolean (true/false/yes/no/on/off/1/0), got: {value!r}"
            )

    foreign = [key for key in keys if key in FOREIGN_KEYS]
    unknown = [key for key in keys if key not in KNOWN_KEYS and key not in FOREIGN_KEYS]
    for key in unknown:
        errors.append(f"unrecognised frontmatter key: {key} (DeepSeek Harness ignores it)")

    return errors, foreign


def fix_skill(path: Path, foreign: list[str]) -> bool:
    """Delete foreign top-level keys. Returns True when the file changed."""
    if not foreign:
        return False
    text = path.read_text(encoding="utf-8")
    split = split_frontmatter(text)
    if split is None:
        return False
    frontmatter, body = split

    kept: list[str] = []
    for line in frontmatter:
        stripped = line.lstrip()
        if not line.startswith((" ", "\t")) and ":" in stripped:
            key = stripped.partition(":")[0].strip()
            if key in foreign:
                continue
        kept.append(line)

    rebuilt = "---\n" + "\n".join(kept).rstrip("\n") + "\n---\n" + body
    if not rebuilt.endswith("\n"):
        rebuilt += "\n"
    path.write_text(rebuilt, encoding="utf-8")
    return True


def discover(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(path.glob("*/SKILL.md")))
            found.extend(sorted(path.glob("*.md")))
        else:
            print(f"skip missing path: {raw}", file=sys.stderr)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=None)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Remove frontmatter keys owned by other agent runtimes.",
    )
    args = parser.parse_args()

    paths = args.paths or [root for root in DEFAULT_ROOTS if Path(root).is_dir()]
    if not paths:
        print("no skill roots found", file=sys.stderr)
        return 1

    skills = discover(paths)
    if not skills:
        print(f"no SKILL.md found under: {', '.join(paths)}", file=sys.stderr)
        return 1

    failed = 0
    fixed = 0
    for skill in skills:
        errors, foreign = lint_skill(skill)
        if args.fix and foreign:
            if fix_skill(skill, foreign):
                fixed += 1
                print(f"fixed  {skill} (removed: {', '.join(foreign)})")
                errors, foreign = lint_skill(skill)
        if errors:
            failed += 1
            print(f"FAIL   {skill}")
            for error in errors:
                print(f"         {error}")
        else:
            print(f"ok     {skill}")

    print()
    print(f"{len(skills)} skills, {failed} failing, {fixed} fixed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
