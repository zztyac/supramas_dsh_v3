from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

try:  # `python scripts/x.py` puts scripts/ on sys.path; `python -m scripts.x` does not.
    import supramas_paths
    from stage_runtime import REPO_ROOT, run_schema_validation, run_stage
except ModuleNotFoundError:  # pragma: no cover - depends on how the script is launched
    from scripts import supramas_paths  # type: ignore[no-redef]
    from scripts.stage_runtime import REPO_ROOT, run_schema_validation, run_stage  # type: ignore[no-redef]


REQUIRED_OUTPUTS = (
    "idea_state.json",
    "idea_pool.json",
    "idea_review_log.jsonl",
    "idea_similarity_graph.json",
    "idea_ranking.json",
    "final_idea_designs.md",
)
IDEA_SCHEMA = supramas_paths.schema_path("idea_design.schema.json")
@dataclass(frozen=True)
class Stage2RunPaths:
    run_dir: Path
    output_dir: Path
    stage1_tree_source: Path

    @property
    def logs_dir(self) -> Path:
        return self.run_dir / "logs"


# Resolved from the asset root, so the prompt works both in a source checkout
# and in an installed bundle, where the caller's workspace holds none of these.
CONTRACT_FILE = supramas_paths.asset_root() / "AGENTS.md"
ROLE_CONTRACT = supramas_paths.agents_dir() / "idea-design-agent.md"

def resolve_path(repo_root: Path, value: Path | str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def generate_run_trace_id(stage: str, job_id: str) -> str:
    return f"supramas:{stage}:{job_id}:{uuid.uuid4().hex}"


def resolve_stage1_tree_source(run_dir: Path) -> Path:
    strategy_tree_path = run_dir / "outputs" / "strategy_tree.json"
    if strategy_tree_path.exists():
        return strategy_tree_path
    tree_state_path = run_dir / "tree_state.json"
    if tree_state_path.exists():
        return tree_state_path
    raise FileNotFoundError(
        f"Stage 2 needs {strategy_tree_path} or {tree_state_path}; neither file exists"
    )


def resolve_run_paths(repo_root: Path, run_dir: Path | str, output_dir: Path | str | None) -> Stage2RunPaths:
    resolved_run_dir = resolve_path(repo_root, run_dir)
    if not resolved_run_dir.exists():
        raise FileNotFoundError(f"run directory not found: {resolved_run_dir}")
    resolved_output_dir = resolve_path(repo_root, output_dir) if output_dir else resolved_run_dir / "stage2"
    stage1_tree_source = resolve_stage1_tree_source(resolved_run_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    (resolved_run_dir / "logs").mkdir(parents=True, exist_ok=True)
    return Stage2RunPaths(
        run_dir=resolved_run_dir,
        output_dir=resolved_output_dir,
        stage1_tree_source=stage1_tree_source,
    )


def build_stage2_prompt(
    paths: Stage2RunPaths,
    run_trace_id: str | None = None,
    *,
    target_final_ideas: int = 5,
    max_iterations: int = 2,
) -> str:
    trace_instruction = (
        f"""
Log-correlation metadata:
- run_trace_id: {run_trace_id}
- Include this run_trace_id in every Stage 2 delegation prompt for session correlation.
- Do not write this run_trace_id into idea_state.json or final_idea_designs.md.
"""
        if run_trace_id
        else ""
    )
    return f"""Act as idea-design-agent for SupraMAS Stage 2 idea innovation.

Read these Stage 2 instructions before doing task work:
{stage2_contracts()}

Routing note:
- The project contract describes the DeepSeek Harness execution model and the delegation tools available to you.
- The user's current task explicitly authorizes Stage 2 idea innovation; do not apply the Stage 1-only boundary to refuse idea design.

Execute this Stage 2 run:
- run_dir: {paths.run_dir}
- stage1_tree_source: {paths.stage1_tree_source}
- output_dir: {paths.output_dir}
- target_final_ideas: {target_final_ideas}
- max_iterations: {max_iterations}
{trace_instruction}

Use the project delegation tools for the full loop, passing each payload in the tool's `prompt`:
- call the `idea_expert` tool for idea generation
- call the `idea_review` tool for review
- call the `idea_proximity` tool for proximity analysis
- call the `idea_ranking` tool for ranking
- call the `idea_evolution` tool for evolution

Do not use any deterministic local runner as the primary execution path. This run must be performed through the Stage 2 agent loop above.

Pipeline:
while not stop_condition:
  idea-expert-agent generates candidate superconducting materials design ideas from Stage 1 evidence
  idea-review-agent reviews every new candidate for evidence, physics, feasibility, risk, and novelty
  idea-proximity-agent updates the similarity graph, duplicate groups, clusters, and underexplored regions
  idea-ranking-agent runs pairwise tournament / cluster-aware ranking over reviewed candidates
  idea-evolution-agent creates new candidates from review, ranking, and proximity feedback
  evolved candidates return to idea-review-agent before ranking or final export
  idea-design-agent updates idea_state and decides whether to continue

Hard requirements:
- Export only review-accepted final ideas.
- Preserve Stage 1 provenance: node_id, paper_id, record_id or limitation_id, chunk_id, and evidence_text.
- Final ideas must include the 15-field material research idea format, including material design plan, tuning_strategy, mechanism pathway, literature basis, validation concept, risk, feasibility, and innovation.
- final_idea_designs.md must be researcher-readable Markdown only. Do not include fenced JSON blocks, raw JSON objects, schema dumps, or compact machine-readable summaries in final_idea_designs.md.
- Put machine-readable records only in idea_state.json, idea_pool.json, idea_similarity_graph.json, idea_ranking.json, and idea_review_log.jsonl.
- Each final idea must include a separate tuning_strategy block with dominant dimensions, concrete Stage 1 tuning_strategy steps, integrated strategy, and controllable variables.
- If a ratio, route, process window, or optimal region is inferred rather than directly stated in evidence, mark it as inferred_design or hypothesis and explain evidence basis, physical rationale, uncertainty, and validation/control.
- Do not fabricate papers, DOI, chunk text, or claim inferred values as evidence-supported.
- Do not export placeholder validation text or broad method menus such as PLD/MOCVD/CSD/MOD/sputtering without a source-linked selected route.
- Stay at idea and validation-concept level; do not write a full experimental protocol.

Write exactly these files under {paths.output_dir}:
- idea_state.json
- idea_pool.json
- idea_review_log.jsonl
- idea_similarity_graph.json
- idea_ranking.json
- final_idea_designs.md

Do not run schema validation yourself: the Python layer validates idea_state.json after you return.

Return a concise execution summary and list the changed file paths."""


def require_output_files(output_dir: Path, final_response: str, logs_dir: Path) -> None:
    """Fail loudly when the idea-design-agent returned without exporting."""
    missing = [name for name in REQUIRED_OUTPUTS if not (output_dir / name).exists()]
    if missing:
        message = "\n".join(
            [
                f"missing Stage 2 output file(s) in {output_dir}: {', '.join(missing)}",
                "",
                "The idea-design-agent returned before completing the full Stage 2 loop.",
                f"Stage 2 session transcript was archived under: {logs_dir / 'dsh_sessions'}",
                "",
                "Last idea-design-agent response:",
                final_response.strip() or "<empty response>",
            ]
        )
        raise FileNotFoundError(message)


def validate_idea_state(repo_root: Path, output_dir: Path) -> tuple[bool, str]:
    """Validate idea_state.json against its schema. Returns `(ok, message)`."""
    return run_schema_validation(
        repo_root=repo_root,
        tree_path=output_dir / "idea_state.json",
        schema_path=IDEA_SCHEMA,
    )


STAGE2_AGENTS = (
    "idea-design-agent", "idea-expert-agent", "idea-review-agent",
    "idea-proximity-agent", "idea-ranking-agent", "idea-evolution-agent",
)
STAGE2_SKILLS = (
    "stage2-idea-design-loop", "superconducting-materials-idea-expert",
    "stage2-idea-review", "stage2-idea-proximity", "stage2-idea-ranking",
    "stage2-idea-evolution",
)


def stage2_contracts() -> str:
    """Absolute paths to the contracts this stage needs.

    Absolute because the bundle lives outside the caller's workspace: a relative
    path would resolve against their project and not exist. Missing entries are
    omitted rather than dangled.
    """
    entries = [supramas_paths.agents_dir() / f"{stem}.md" for stem in STAGE2_AGENTS]
    skills_root = supramas_paths.skills_dir()
    if skills_root:
        entries += [skills_root / name / "SKILL.md" for name in STAGE2_SKILLS]
    sop = supramas_paths.asset_root() / "docs" / "stage2_idea_design_sop.md"
    entries.append(sop)
    return "\n".join(f"- {path}" for path in entries if path.is_file())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SupraMAS Stage 2 idea innovation on DeepSeek Harness."
    )
    parser.add_argument("--run-dir", type=Path, required=True, help="Path to runs/{job_id}")
    parser.add_argument("--output-dir", type=Path, help="Override output directory; defaults to run_dir/stage2")
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
    parser.add_argument("--target-final-ideas", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=2)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=0,
        help="Abort the stage run after this many seconds; 0 waits indefinitely.",
    )
    parser.add_argument(
        "--skip-schema-check",
        action="store_true",
        help="Do not validate idea_state.json against schemas/idea_design.schema.json.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = supramas_paths.workspace()
    paths = resolve_run_paths(repo_root, args.run_dir, args.output_dir)
    print(f"[stage2] run_dir: {paths.run_dir}", flush=True)
    print(f"[stage2] stage1_tree_source: {paths.stage1_tree_source}", flush=True)
    print(f"[stage2] output_dir: {paths.output_dir}", flush=True)
    print(f"[stage2] session_archive_dir: {paths.logs_dir / 'dsh_sessions'}", flush=True)
    run_trace_id = generate_run_trace_id("stage2", paths.run_dir.name)
    print(f"[stage2] run_trace_id: {run_trace_id}", flush=True)
    print("[stage2] waiting for idea-design-agent...", flush=True)

    result = run_stage(
        build_stage2_prompt(
            paths,
            run_trace_id,
            target_final_ideas=args.target_final_ideas,
            max_iterations=args.max_iterations,
        ),
        repo_root=repo_root,
        stage="stage2",
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
            f"idea-design-agent run failed with exit code {result.exit_code}; "
            f"session transcript: {result.session_archive or paths.logs_dir / 'dsh_sessions'}"
        )

    require_output_files(paths.output_dir, result.final_text, paths.logs_dir)

    if not args.skip_schema_check:
        ok, message = validate_idea_state(repo_root, paths.output_dir)
        if not ok:
            print(message, file=sys.stderr)
            raise RuntimeError("idea_state.json failed JSON Schema validation")
        print(f"[stage2] schema validation passed: {paths.output_dir / 'idea_state.json'}", flush=True)

    print(f"stage2 outputs ready: {paths.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
