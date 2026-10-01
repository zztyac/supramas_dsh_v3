#!/usr/bin/env python3
"""Shared DeepSeek Harness runtime for the SupraMAS stage scripts.

Replaces the per-script `openai_codex` bridge, the Codex hook registry, and the
Codex session exporter with three responsibilities:

1. Drive one stage through `scripts/dsh_runner.py`.
2. Archive the DeepSeek Harness session transcript and write a manifest.
3. Close Stage 1 deterministically with `tools/assemble_strategy_tree.py`.

Point 3 is the reason this module exists. Before the migration the coordinator
agent wrote the three exported artifacts *and* ran the schema check against its
own output. The assembler derives those artifacts from `tree_state.json` under
full validation instead, which removes that self-certification gap.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:  # `python scripts/x.py` puts scripts/ on sys.path; `python -m scripts.x` does not.
    import supramas_paths
    from dsh_runner import DEFAULT_PATCH, DshRunner, DshRunResult, require_output_files
except ModuleNotFoundError:  # pragma: no cover - depends on how the script is launched
    from scripts import supramas_paths  # type: ignore[no-redef]
    from scripts.dsh_runner import (  # type: ignore[no-redef]
        DEFAULT_PATCH,
        DshRunner,
        DshRunResult,
        require_output_files,
    )

# See supramas_paths: the asset root holds tools/, schemas/ and the bundle
# patch; the workspace is the caller's project, where runs/ are written.
ASSET_ROOT = supramas_paths.asset_root()
WORKSPACE = supramas_paths.workspace()

# Retained so existing importers keep working; it is the ASSET root, not the
# workspace.
REPO_ROOT = ASSET_ROOT

__all__ = [
    "DEFAULT_PATCH",
    "REPO_ROOT",
    "archive_dir_for",
    "manifest_path_for",
    "require_output_files",
    "run_deterministic_assembly",
    "run_schema_validation",
    "run_stage",
    "write_session_manifest",
]


def archive_dir_for(logs_dir: Path) -> Path:
    """Where archived DeepSeek Harness sessions live for a run."""
    return logs_dir / "dsh_sessions"


def manifest_path_for(logs_dir: Path, stage: str) -> Path:
    return logs_dir / f"{stage}_dsh_session_manifest.jsonl"


def run_stage(
    prompt: str,
    *,
    repo_root: Path,
    stage: str,
    logs_dir: Path,
    model: str | None = None,
    provider: str | None = None,
    permission_mode: str | None = None,
    patch: Path | None = DEFAULT_PATCH,
    timeout_seconds: float = 0,
) -> DshRunResult:
    """Run one stage task on DeepSeek Harness and archive its transcript."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    events_out = logs_dir / f"{stage}_events.jsonl"

    with DshRunner(
        repo_root=repo_root,
        patch=patch,
        model=model,
        provider=provider,
        permission_mode=permission_mode,
    ) as runner:
        result = runner.run(
            prompt,
            events_out=events_out,
            archive_session_to=archive_dir_for(logs_dir),
            timeout_seconds=timeout_seconds,
        )

    write_session_manifest(logs_dir, stage, result)
    return result


def write_session_manifest(logs_dir: Path, stage: str, result: DshRunResult) -> Path:
    """Record how a stage run ended, replacing the Codex session manifest.

    Subagent sessions are archived alongside the parent, so the manifest lists
    every transcript that belongs to the run rather than only the top-level one.
    """
    path = manifest_path_for(logs_dir, stage)
    archives = result.session_archives or ([result.session_archive] if result.session_archive else [])
    record = {
        "stage": stage,
        "session_id": result.session_id,
        "exit_code": result.exit_code,
        "ok": result.ok,
        "events_path": str(result.events_path) if result.events_path else None,
        "session_archive": str(result.session_archive) if result.session_archive else None,
        "archive_dir": str(archive_dir_for(logs_dir)),
        "archived_session_count": len(archives),
        "archived_sessions": [
            {"session_id": archive.name, "path": str(archive), "is_subagent": not archive.name.startswith("session-")}
            for archive in archives
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def run_deterministic_assembly(
    *,
    repo_root: Path,
    input_task: Path,
    tree_state: Path,
    output_dir: Path,
    check_only: bool = True,
) -> subprocess.CompletedProcess:
    """Validate (and optionally export) the strategy tree from `tree_state.json`.

    With `check_only=True` this is a pure gate: it runs the assembler's frontier
    closure, edge consistency, and evidence-chunk validation without writing
    anything.
    """
    command = [
        sys.executable,
        str(repo_root / "tools" / "assemble_strategy_tree.py"),
        "--input-task",
        str(input_task),
        "--state",
        str(tree_state),
    ]
    if check_only:
        command.append("--check-only")
    else:
        command += ["--output-dir", str(output_dir)]
    return subprocess.run(
        command, cwd=repo_root, capture_output=True, text=True, check=False
    )


def run_schema_validation(
    *, repo_root: Path, tree_path: Path, schema_path: Path
) -> tuple[bool, str]:
    """Validate an exported artifact against its JSON Schema.

    Returns `(ok, message)`. `scripts/validate_schema.py` prefers `jsonschema`
    when installed and falls back to the bundled subset validator, so this gate
    always runs instead of quietly disappearing on a machine without the
    optional dependency.
    """
    completed = subprocess.run(
        [
            sys.executable,
            # The validator ships with the ASSETS, not with the caller's project.
            str(ASSET_ROOT / "scripts" / "validate_schema.py"),
            str(tree_path),
            "--schema",
            str(schema_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0, (completed.stdout + completed.stderr).strip()
