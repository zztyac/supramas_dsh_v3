#!/usr/bin/env python3
"""Convert .codex/agents/*.toml role contracts into DSH role-contract Markdown.

DSH carries roles as `dsh-tool-subagent` personas (plain Markdown read by the
bundle patch) instead of Codex custom agent types. This converter is deliberately
mechanical: it strips the TOML wrapper and the Codex/Claude-specific prose, and
rewrites delegation instructions to the DSH named-tool names. Every domain
contract (tuning dimensions, record separation, edge types, evidence discipline)
is preserved byte-for-byte.

Usage:
    PYTHONDONTWRITEBYTECODE=1 python3 scripts/migrate_codex_agents_to_dsh.py \
        --source .codex/agents --dest packages/supramas-dsh/agents [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Codex agent type -> DSH subagent tool name.
TOOL_NAMES = {
    "strategy-builder-agent": "strategy_builder",
    "strategy-tree-reviewer": "strategy_reviewer",
    "idea-expert-agent": "idea_expert",
    "idea-review-agent": "idea_review",
    "idea-proximity-agent": "idea_proximity",
    "idea-ranking-agent": "idea_ranking",
    "idea-evolution-agent": "idea_evolution",
}

# Roles that run as the main-session persona rather than as a delegation tool.
COORDINATOR_ROLES = {"strategy-mining-agent", "task-setup-agent", "idea-design-agent"}

DELEGATION_TOOLS = {
    "strategy-mining-agent": ["strategy_builder", "strategy_reviewer"],
    "idea-design-agent": [
        "idea_expert",
        "idea_review",
        "idea_proximity",
        "idea_ranking",
        "idea_evolution",
    ],
    "task-setup-agent": [],
}

# Inner-frontmatter keys that have no DSH equivalent and are dropped.
DROPPED_FRONTMATTER_KEYS = {
    "runtime",
    "codex_agent_type",
    "uses_role_prompts",
    "uses_skill_specs",
    "sandbox_mode",
}

# Ordered literal rewrites applied to the contract body. Longest first.
REWRITES: list[tuple[str, str]] = [
    (
        "This is a project-scoped Codex custom agent instruction. "
        "In Codex, execute this role by spawning `{role}` directly when using subagents.",
        "",
    ),
    (
        "This is a project-scoped Codex custom agent instruction. "
        "In Codex, execute this role in the main session or spawn `strategy-mining-agent` "
        "directly when using subagents.",
        "",
    ),
    ("This is a project-scoped Codex custom agent instruction.", ""),
    (
        "In Codex, this role is normally executed in the main session, because task setup "
        "may require interaction. A generic `worker` may read this TOML file only for a "
        "bounded, non-interactive draft/check, and must obey the worker restrictions below.",
        "",
    ),
    (
        "A Codex worker cannot truly converse with the user. Therefore:",
        "A delegated subagent cannot truly converse with the user. Therefore:",
    ),
    ("Codex delegation rules:", "Subagent delegation rules:"),
    ("Codex delegation", "Subagent delegation"),
    ("a Codex worker", "a subagent"),
    ("the main Codex session", "the main session"),
    ("main Codex session", "main session"),
    ("Do not use Claude named-agent syntax.", ""),
    ("Do not use Claude named-agent syntax", ""),
]

DELEGATION_REWRITES = [
    (
        "spawn or task a Codex worker acting as `strategy-builder-agent`",
        "call the `strategy_builder` tool",
    ),
    (
        "spawn or task a Codex worker acting as `strategy-tree-reviewer`",
        "call the `strategy_reviewer` tool",
    ),
    ("spawn a background `task-setup-agent` worker", "delegate to a background subagent"),
    ("builder/reviewer workers", "builder/reviewer subagents"),
]

SKILL_GUIDANCE = {
    "research-lit": "`research-lit`",
    "arxiv": "`arxiv`",
    "semantic-scholar": "`semantic-scholar`",
    "openalex": "`openalex`",
    "deepxiv": "`deepxiv`",
    "exa-search": "`exa-search`",
    "strategy-tree-builder": "`strategy-tree-builder`",
    "strategy-tree-validation": "`strategy-tree-validation`",
}


def parse_toml(path: Path) -> dict:
    """Extract the fields this migration needs, without a TOML dependency."""
    text = path.read_text(encoding="utf-8")
    data: dict = {}

    for key in ("name", "description", "sandbox_mode"):
        match = re.search(rf'^{key}\s*=\s*"((?:[^"\\]|\\.)*)"\s*$', text, re.MULTILINE)
        if match:
            data[key] = match.group(1)

    match = re.search(r"^developer_instructions\s*=\s*'''(.*?)'''", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise SystemExit(f"{path}: developer_instructions block not found")
    data["developer_instructions"] = match.group(1)
    return data


def split_inner_frontmatter(block: str) -> tuple[dict, str]:
    """Split the role contract's own YAML frontmatter from its body."""
    text = block.lstrip("\n")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4 :].lstrip("\n")

    meta: dict = {}
    current_list: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current_list:
            meta.setdefault(current_list, []).append(line.strip()[2:].strip().strip("\"'"))
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                meta[key] = value.strip("\"'")
                current_list = None
            else:
                meta[key] = []
                current_list = key
    return meta, body


def apply_rewrites(body: str) -> str:
    for old, new in DELEGATION_REWRITES:
        body = body.replace(old, new)
    for old, new in REWRITES:
        if "{role}" in old:
            for role in TOOL_NAMES:
                body = body.replace(old.format(role=role), new)
        else:
            body = body.replace(old, new)

    # Any remaining Codex custom-agent type name becomes its DSH tool name.
    for role, tool in TOOL_NAMES.items():
        body = body.replace(f"`{role}`", f"`{tool}`")
        body = body.replace(role, tool)

    # Collapse the blank-line runs the deletions may leave behind.
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip() + "\n"


def build_markdown(name: str, description: str, meta: dict, body: str) -> str:
    """Render one DSH role contract."""
    parts: list[str] = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "---",
        "",
        f"# {name}",
        "",
    ]

    is_coordinator = name in COORDINATOR_ROLES
    if is_coordinator:
        parts += [
            "Execution model: this role runs as the main session persona in DeepSeek Harness.",
            "",
        ]
    else:
        parts += [
            "Execution model: this role runs as a delegated subagent in DeepSeek Harness, "
            "configured by the SupraMAS bundle patch.",
            "",
        ]

    tools = DELEGATION_TOOLS.get(name, [])
    if tools:
        parts += [
            "Delegation tools available to this role: "
            + ", ".join(f"`{tool}`" for tool in tools)
            + ". Prefer starting independent delegations together in one message and "
            "continuing useful work while they run.",
            "",
        ]

    skills = meta.get("uses_skill_specs") or []
    if isinstance(skills, str):
        skills = [skills]
    if skills:
        rendered = [SKILL_GUIDANCE.get(skill, f"`{skill}`") for skill in skills]
        parts += [
            "Skill assembly: load the skills you need with the `skill` tool. "
            "This role relies on " + ", ".join(rendered) + ".",
            "",
        ]

    parts.append(body.rstrip() + "\n")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".codex/agents")
    parser.add_argument("--dest", default="packages/supramas-dsh/agents")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the destination is out of date instead of writing it.",
    )
    args = parser.parse_args()

    source = Path(args.source)
    dest = Path(args.dest)
    if not source.is_dir():
        print(f"source directory not found: {source}", file=sys.stderr)
        return 1

    toml_files = sorted(source.glob("*.toml"))
    if not toml_files:
        print(f"no *.toml role contracts found in {source}", file=sys.stderr)
        return 1

    if not args.check:
        dest.mkdir(parents=True, exist_ok=True)

    stale: list[str] = []
    written = 0
    for path in toml_files:
        data = parse_toml(path)
        name = data.get("name") or path.stem
        description = data.get("description") or ""
        meta, raw_body = split_inner_frontmatter(data["developer_instructions"])
        meta.pop("name", None)
        meta.pop("description", None)
        for key in DROPPED_FRONTMATTER_KEYS:
            meta.pop(key, None)

        markdown = build_markdown(name, description, meta, apply_rewrites(raw_body))
        target = dest / f"{name}.md"

        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else None
            if current != markdown:
                stale.append(str(target))
            continue

        target.write_text(markdown, encoding="utf-8")
        written += 1
        print(f"wrote {target} ({len(markdown)} bytes)")

    if args.check:
        if stale:
            print("out of date:\n  " + "\n  ".join(stale), file=sys.stderr)
            return 1
        print(f"up to date: {len(toml_files)} role contracts")
        return 0

    print(f"converted {written} role contracts into {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
