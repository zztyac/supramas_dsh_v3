from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

try:  # `python scripts/x.py` puts scripts/ on sys.path; `python -m scripts.x` does not.
    import supramas_paths
    from stage_runtime import (
        REPO_ROOT,
        run_deterministic_assembly,
        run_schema_validation,
        run_stage,
    )
except ModuleNotFoundError:  # pragma: no cover - depends on how the script is launched
    from scripts import supramas_paths  # type: ignore[no-redef]
    from scripts.stage_runtime import (  # type: ignore[no-redef]
        REPO_ROOT,
        run_deterministic_assembly,
        run_schema_validation,
        run_stage,
    )

# Resolved from the asset root, so the prompt works both in a source checkout
# and in an installed bundle, where the caller's workspace holds none of these.
CONTRACT_FILE = supramas_paths.asset_root() / "AGENTS.md"
ROLE_CONTRACT = supramas_paths.agents_dir() / "strategy-mining-agent.md"


REQUIRED_OUTPUTS = ("strategy_tree.json", "node_review_log.jsonl", "review_report.md")
DEFAULT_SCHEMA = supramas_paths.schema_path("strategy_tree.schema.json")


@dataclass(frozen=True)
class RunPaths:
    input_task: Path
    run_dir: Path
    output_dir: Path

    @property
    def logs_dir(self) -> Path:
        return self.run_dir / "logs"

    @property
    def papers_dir(self) -> Path:
        return self.run_dir / "papers"


def resolve_path(repo_root: Path, value: Path | str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def generate_run_trace_id(stage: str, job_id: str) -> str:
    return f"supramas:{stage}:{job_id}:{uuid.uuid4().hex}"


def resolve_run_paths(
    repo_root: Path,
    input_task: Path,
    run_dir: Path | None,
    output_dir: Path | None,
) -> RunPaths:
    resolved_input_task = resolve_path(repo_root, input_task)
    if not resolved_input_task.exists():
        raise FileNotFoundError(f"input task not found: {resolved_input_task}")
    resolved_run_dir = resolve_path(repo_root, run_dir) if run_dir else resolved_input_task.parent
    resolved_output_dir = resolve_path(repo_root, output_dir) if output_dir else resolved_run_dir / "outputs"
    (resolved_run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (resolved_run_dir / "papers").mkdir(parents=True, exist_ok=True)
    return RunPaths(
        input_task=resolved_input_task,
        run_dir=resolved_run_dir,
        output_dir=resolved_output_dir,
    )


def build_stage1_prompt(paths: RunPaths, run_trace_id: str | None = None, *, resume: bool = False) -> str:
    trace_instruction = (
        f"""
Log-correlation metadata:
- run_trace_id: {run_trace_id}
- Include this run_trace_id in every `strategy_builder` and `strategy_reviewer` delegation prompt for session correlation.
- Do not write this run_trace_id into strategy_tree.json, node_review_log.jsonl, or review_report.md.
"""
        if run_trace_id
        else ""
    )
    resume_instruction = (
        f"""
Resume mode:
- Load the existing tree_state.json at {paths.run_dir / "tree_state.json"} before starting any builder or reviewer work.
- Treat tree_state.json as authoritative for accepted tree.nodes, tree.edges, frontier_status, review_log, and attempt summaries.
- Do not rebuild accepted nodes or accepted edges already present in tree_state.json.
- Continue only frontier_status entries whose status is pending, open, review_pending, pending_review_queue, waiting_on_revise, or otherwise non-terminal.
- For frontier entries with builder-returned candidates awaiting review, review those existing candidates before launching a new literature-search attempt.
- Preserve existing node_id, record_id, limitation_id, paper_id, and evidence.chunk_id values when resuming.
- Update tree_state.json after every resumed reviewer decision, retry, terminal frontier status, accepted node, and accepted edge.
"""
        if resume
        else ""
    )
    return f"""Act as strategy-mining-agent for SupraMAS Stage 1.

Read the project contract at {CONTRACT_FILE} and the role contract at {ROLE_CONTRACT} before doing task work.

Execute this task:
- input_task_path: {paths.input_task}
- run_dir: {paths.run_dir}
- output_dir: {paths.output_dir}
- papers_dir: {paths.papers_dir}
{trace_instruction}
{resume_instruction}

Use the project delegation tools for construction and review:
- call the `strategy_builder` tool with the builder task payload in `prompt`
- call the `strategy_reviewer` tool with the node/edge payload in `prompt`

Keep all project task fields inside each delegation prompt, including papers_dir={paths.papers_dir}.

Input task scope semantics:
- Treat research_topic, material_scope, target_property, and constraints.include/exclude as topic-shaping guidance for Stage 1 literature mining, not as hard acceptance filters for every paper node.
- Prefer exact matches, but if no single paper satisfies all narrow task phrases, build from the closest evidence-rich adjacent strategy papers in the superconducting materials / REBCO flux-pinning space.
- Record missing task-specific details as coverage gaps in review_report.md; do not reject an otherwise useful node solely for missing a downstream idea-design detail unless the task explicitly labels that detail as a hard Stage 1 node requirement.

Paper persistence for this run:
- save every downloaded paper, paper metadata file, and parsed evidence chunk used by a node under {paths.papers_dir};
- pass papers_dir={paths.papers_dir} to every `strategy_builder` and `strategy_reviewer` task;
- require builder returns to cite evidence.chunk_id values that resolve to files under {paths.papers_dir};
- require reviewer checks to verify chunks under {paths.papers_dir};
- strategy-builder-agent must use its literature-search skills to find root and child candidates, then persist the selected evidence under {paths.papers_dir}.

Follow the Stage 1 boundary strictly:
- build only a literature-grounded strategy tree;
- do not generate ideas, protocols, Bayesian optimization plans, real-world feedback loops, or hierarchical backtracking;
- add only reviewer-accepted nodes and edges;
- save every paper used by a node under {paths.papers_dir};
- ensure every evidence.chunk_id resolves to a saved local chunk.

State persistence and completion discipline:
- Maintain the live build state at {paths.run_dir / "tree_state.json"}.
- Write or update tree_state.json after every accepted root, reviewer decision, builder retry, frontier status change, accepted edge, and exhausted-attempt decision.
- Preserve enough state to resume: tree.nodes, tree.edges, frontier_status, review_log, and attempt summaries.
- Do not return a final response while any frontier limitation is pending, open, or waiting on revise.
- If a reviewer returns revise and the same paper can be corrected, continue the same builder/reviewer loop until accept or reject; if critical evidence issues remain after repeated revision, reject that paper attempt and continue according to max_child_attempts_per_limitation.

Strict single-run completion mode:
- Do not write stage1_incomplete.json as a planned or normal stopping condition.
- Do not return a final response until every reachable frontier limitation has a terminal status and the final artifacts have been exported.
- Continue builder/reviewer work while any frontier_status entry is pending, open, review_pending, pending_review_queue, waiting_on_revise, or otherwise non-terminal.
- If a task is scientifically unsupported after the configured attempt budget, mark that frontier with a terminal exhausted status and continue the remaining frontier queue.
- If execution becomes impossible because of a fatal tool, filesystem, or schema error, return an explicit fatal error summary instead of writing stage1_incomplete.json.

When finished, export exactly these files under {paths.output_dir}:
- strategy_tree.json
- node_review_log.jsonl
- review_report.md

Do not run schema validation yourself: the Python layer validates {
  paths.output_dir / "strategy_tree.json"} after you return and will reject an invalid tree.

Return a concise execution summary and list the changed file paths."""


def require_output_files(output_dir: Path, final_response: str, logs_dir: Path) -> None:
    """Fail loudly when the strategy-mining-agent returned without exporting."""
    missing = [name for name in REQUIRED_OUTPUTS if not (output_dir / name).exists()]
    if missing:
        message = "\n".join(
            [
                f"missing Stage 1 output file(s) in {output_dir}: {', '.join(missing)}",
                "",
                "The strategy-mining-agent returned before strict single-run completion.",
                "No stage1_incomplete.json was written; this is a hard failure under strict completion mode.",
                f"Stage 1 session transcript was archived under: {logs_dir / 'dsh_sessions'}",
                "",
                "Last strategy-mining-agent response:",
                final_response.strip() or "<empty response>",
            ]
        )
        raise FileNotFoundError(message)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a SupraMAS Stage 1 strategy tree on DeepSeek Harness."
    )
    parser.add_argument("--input-task", type=Path, required=True, help="Path to runs/{job_id}/input_task.yaml")
    parser.add_argument("--run-dir", type=Path, help="Override run directory; defaults to input_task.yaml parent")
    parser.add_argument("--output-dir", type=Path, help="Override output directory; defaults to run_dir/outputs")
    parser.add_argument(
        "--model",
        help="Override the profile's agent-default-model for this run (provider/model).",
    )
    parser.add_argument("--provider", help="Provider for --model; omit to keep the profile's provider.")
    parser.add_argument(
        "--permission-mode",
        choices=("read-only", "workspace-write", "danger-full-access"),
        help="Sets DSH_PERMISSION_MODE. Unattended runs must not rely on the approval default.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=0,
        help="Abort the stage run after this many seconds; 0 waits indefinitely.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from run_dir/tree_state.json instead of starting the Stage 1 coordinator from scratch.",
    )
    parser.add_argument(
        "--skip-assembly-check",
        action="store_true",
        help="Do not run the deterministic assembly gate on run_dir/tree_state.json.",
    )
    parser.add_argument(
        "--deterministic-export",
        action="store_true",
        help=(
            "Require run_dir/tree_state.json and let tools/assemble_strategy_tree.py write the "
            "three artifacts, instead of accepting artifacts written by the agent."
        ),
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help="JSON Schema used to validate the exported strategy tree.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = supramas_paths.workspace()
    paths = resolve_run_paths(repo_root, args.input_task, args.run_dir, args.output_dir)
    tree_state = paths.run_dir / "tree_state.json"

    print(f"[stage1] run_dir: {paths.run_dir}", flush=True)
    print(f"[stage1] output_dir: {paths.output_dir}", flush=True)
    print(f"[stage1] papers_dir: {paths.papers_dir}", flush=True)
    print(f"[stage1] session_archive_dir: {paths.logs_dir / 'dsh_sessions'}", flush=True)

    if (args.resume or args.deterministic_export) and not tree_state.exists():
        raise FileNotFoundError(
            f"--resume/--deterministic-export requires the live build state: {tree_state}"
        )
    if args.resume:
        print(f"[stage1] resume_state: {tree_state}", flush=True)

    run_trace_id = generate_run_trace_id("stage1", paths.run_dir.name)
    print(f"[stage1] run_trace_id: {run_trace_id}", flush=True)
    print("[stage1] waiting for strategy-mining-agent...", flush=True)

    result = run_stage(
        build_stage1_prompt(paths, run_trace_id, resume=args.resume),
        repo_root=repo_root,
        stage="stage1",
        logs_dir=paths.logs_dir,
        model=args.model,
        provider=args.provider,
        permission_mode=args.permission_mode,
        timeout_seconds=args.timeout_seconds,
    )
    print(result.summary(), file=sys.stderr)
    print(result.final_text)
    if not result.ok:
        raise RuntimeError(
            f"strategy-mining-agent run failed with exit code {result.exit_code}; "
            f"session transcript: {result.session_archive or paths.logs_dir / 'dsh_sessions'}"
        )

    # Deterministic closing step. The coordinator agent maintains tree_state.json;
    # the assembler derives (or at minimum validates) the exported artifacts under
    # full frontier/edge/evidence validation.
    if args.deterministic_export:
        print("[stage1] assembling deterministic outputs from tree_state.json...", flush=True)
        completed = run_deterministic_assembly(
            repo_root=repo_root,
            input_task=paths.input_task,
            tree_state=tree_state,
            output_dir=paths.output_dir,
            check_only=False,
        )
        if completed.returncode != 0:
            print(completed.stdout, file=sys.stderr)
            print(completed.stderr, file=sys.stderr)
            raise RuntimeError("deterministic assembly failed; refusing to export an invalid tree")
        print(completed.stdout.strip(), flush=True)
    elif not args.skip_assembly_check and tree_state.exists():
        print("[stage1] verifying tree_state.json with the deterministic assembler...", flush=True)
        completed = run_deterministic_assembly(
            repo_root=repo_root,
            input_task=paths.input_task,
            tree_state=tree_state,
            output_dir=paths.output_dir,
            check_only=True,
        )
        if completed.returncode != 0:
            print(completed.stdout, file=sys.stderr)
            print(completed.stderr, file=sys.stderr)
            raise RuntimeError(
                "assemble_strategy_tree.py rejected tree_state.json; "
                "the exported tree is not structurally sound"
            )
        print(completed.stdout.strip(), flush=True)
    elif not args.skip_assembly_check:
        print(
            f"[stage1] WARNING: {tree_state} is missing; skipped the deterministic assembly gate.",
            flush=True,
        )

    require_output_files(paths.output_dir, result.final_text, paths.logs_dir)

    schema_path = args.schema if args.schema.is_absolute() else repo_root / args.schema
    ok, message = run_schema_validation(
        repo_root=repo_root,
        tree_path=paths.output_dir / "strategy_tree.json",
        schema_path=schema_path,
    )
    if not ok:
        print(message, file=sys.stderr)
        raise RuntimeError("strategy_tree.json failed JSON Schema validation")
    print(f"[stage1] schema validation passed: {paths.output_dir / 'strategy_tree.json'}", flush=True)

    print(f"stage1 outputs ready: {paths.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
