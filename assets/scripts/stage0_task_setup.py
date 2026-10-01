from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:  # `python scripts/x.py` puts scripts/ on sys.path; `python -m scripts.x` does not.
    import supramas_paths
    from stage_runtime import REPO_ROOT, run_stage
except ModuleNotFoundError:  # pragma: no cover - depends on how the script is launched
    from scripts import supramas_paths  # type: ignore[no-redef]
    from scripts.stage_runtime import REPO_ROOT, run_stage  # type: ignore[no-redef]

# Resolved from the asset root, so the prompt works both in a source checkout
# and in an installed bundle, where the caller's workspace holds none of these.
CONTRACT_FILE = supramas_paths.asset_root() / "AGENTS.md"
ROLE_CONTRACT = supramas_paths.agents_dir() / "task-setup-agent.md"


@dataclass(frozen=True)
class TaskSetupPaths:
    job_id: str
    run_dir: Path
    input_task: Path
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


def generate_timestamp_job_id(now: datetime | None = None) -> str:
    timestamp = now if now is not None else datetime.now()
    return timestamp.strftime("%Y%m%d_%H%M%S")


def generate_run_trace_id(stage: str, job_id: str) -> str:
    return f"supramas:{stage}:{job_id}:{uuid.uuid4().hex}"


def prepare_run_paths(
    repo_root: Path,
    job_id: str | None,
    run_dir: Path | None,
    overwrite: bool,
    now: datetime | None = None,
) -> TaskSetupPaths:
    if run_dir:
        resolved_run_dir = resolve_path(repo_root, run_dir)
        resolved_job_id = job_id or resolved_run_dir.name
    else:
        resolved_job_id = job_id or generate_timestamp_job_id(now)
        resolved_run_dir = repo_root / "runs" / resolved_job_id
    input_task = resolved_run_dir / "input_task.yaml"
    output_dir = resolved_run_dir / "outputs"
    logs_dir = resolved_run_dir / "logs"
    papers_dir = resolved_run_dir / "papers"
    if input_task.exists() and not overwrite:
        raise FileExistsError(f"input_task.yaml already exists: {input_task}")
    resolved_run_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    papers_dir.mkdir(parents=True, exist_ok=True)
    return TaskSetupPaths(
        job_id=resolved_job_id,
        run_dir=resolved_run_dir,
        input_task=input_task,
        output_dir=output_dir,
    )


def build_task_setup_prompt(
    paths: TaskSetupPaths,
    research_goal: str,
    use_defaults: bool,
    overwrite: bool,
    run_trace_id: str | None = None,
) -> str:
    defaults_instruction = (
        "The user has approved defaults: use_defaults=true."
        if use_defaults
        else "Defaults are not pre-approved. If required fields are missing, return needs_user_input and do not write the file."
    )
    overwrite_instruction = (
        "The user explicitly allows overwriting an existing input_task.yaml."
        if overwrite
        else "Do not overwrite an existing input_task.yaml."
    )
    trace_instruction = (
        f"""
Log-correlation metadata:
- run_trace_id: {run_trace_id}
- Use this value only for DeepSeek Harness session correlation; do not copy it into input_task.yaml.
"""
        if run_trace_id
        else ""
    )
    return f"""Act as task-setup-agent.

Read the project contract at {CONTRACT_FILE} and the role contract at {ROLE_CONTRACT} before doing task work.

Create or refine a SupraMAS Stage 1 task definition from this research goal:
{research_goal}

Task setup target:
- job_id: {paths.job_id}
- run_dir: {paths.run_dir}
- input_task_path: {paths.input_task}
- output_dir: {paths.output_dir}
- papers_dir: {paths.papers_dir}
- naming_policy: timestamp-derived job_id by default; keep the YAML job_id and output_dir aligned with this run directory.
{trace_instruction}

{defaults_instruction}
{overwrite_instruction}

Follow the task-setup-agent contract:
- create the run directory if needed;
- write exactly {paths.input_task} when the task payload is complete or defaults are approved;
- keep output_dir as {paths.output_dir};
- include papers_dir as {paths.papers_dir};
- Use Chinese for user-facing questions and final summaries.
- use Stage 1 only;
- use strict literature evidence policy: strategy-builder-agent must search literature through its research skills, then persist every selected paper and evidence chunk under papers_dir;
- Do not search literature;
- do not call strategy-builder-agent or strategy-tree-reviewer;
- do not build strategy_tree.json.

Return the created path, normalized research topic, assumptions, and the next command to run strategy-mining-agent. If more user input is needed, return the task-setup-agent needs_user_input JSON only."""


def parse_json_response(response: str) -> object | None:
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None


def format_list(values: object) -> str:
    if isinstance(values, list):
        return "、".join(str(value) for value in values)
    if values is None:
        return "未给出"
    return str(values)


def format_task_setup_response(response: str) -> str:
    parsed = parse_json_response(response)
    if not isinstance(parsed, dict):
        return response
    if parsed.get("status") != "needs_user_input":
        return response

    interpretation = parsed.get("interpretation")
    if not isinstance(interpretation, dict):
        interpretation = {}
    defaults = parsed.get("proposed_defaults")
    questions = parsed.get("questions")

    lines = [
        "[stage0] task-setup-agent 需要你补充信息",
        "",
        "当前理解：",
        f"- 研究主题: {interpretation.get('research_topic', '未给出')}",
        f"- 材料范围: {format_list(interpretation.get('material_scope'))}",
        f"- 目标性能: {format_list(interpretation.get('target_property'))}",
    ]
    if defaults:
        lines.extend(
            [
                "",
                "建议默认设置：",
                json.dumps(defaults, ensure_ascii=False, indent=2),
            ]
        )
    if isinstance(questions, list) and questions:
        lines.extend(["", "请回答下面的问题，可以合并成一段回答："])
        lines.extend(f"{index}. {question}" for index, question in enumerate(questions, start=1))
    return "\n".join(lines)

def build_followup_prompt(answers: list[str], input_task: Path | None) -> str:
    target = f"\nTarget input_task_path remains: {input_task}" if input_task else ""
    answered = "\n".join(f"{index}. {answer}" for index, answer in enumerate(answers, start=1))
    return f"""用户补充回答（按轮次）：
{answered}
{target}

You are starting a fresh session with no prior conversation. Re-read
{ROLE_CONTRACT} and {CONTRACT_FILE}, then continue task setup.
若信息已经足够，请写入 input_task.yaml；若仍不足，请只返回下一轮 needs_user_input JSON。"""


def run_task_setup(
    prompt: str,
    *,
    repo_root: Path,
    input_task: Path | None,
    logs_dir: Path,
    interactive: bool,
    max_turns: int,
    model: str | None = None,
    provider: str | None = None,
    permission_mode: str | None = None,
    timeout_seconds: float = 0,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> str:
    """Run Stage 0 task setup on DeepSeek Harness.

    A DeepSeek Harness headless run handles exactly one task and has no
    interactive follow-up, so each clarification round is a fresh run whose prompt
    carries every answer collected so far.
    """

    def one_run(task_prompt: str) -> str:
        result = run_stage(
            task_prompt,
            repo_root=repo_root,
            stage="stage0",
            logs_dir=logs_dir,
            model=model,
            provider=provider,
            permission_mode=permission_mode,
            timeout_seconds=timeout_seconds,
        )
        if not result.ok:
            raise RuntimeError(
                f"task-setup-agent run failed with exit code {result.exit_code}; "
                f"session transcript: {result.session_archive or logs_dir / 'dsh_sessions'}"
            )
        return result.final_text

    response = one_run(prompt)
    if input_task and input_task.exists():
        return response
    if not interactive:
        return response

    answers: list[str] = []
    for _ in range(max(0, max_turns - 1)):
        output_func(format_task_setup_response(response))
        answer = input_func("请回答 task-setup-agent 的问题（直接回车结束）：").strip()
        if not answer:
            return response
        answers.append(answer)
        response = one_run(build_followup_prompt(answers, input_task))
        if input_task and input_task.exists():
            return response
    return response

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a SupraMAS Stage 1 input_task.yaml on DeepSeek Harness."
    )
    parser.add_argument("--research-goal", required=True, help="Free-form Stage 1 research goal")
    parser.add_argument("--job-id", help="Override timestamp-derived run id; creates runs/{job_id}/")
    parser.add_argument("--run-dir", type=Path, help="Override run directory; defaults to runs/{timestamp}")
    parser.add_argument(
        "--use-defaults",
        action="store_true",
        help="Tell task-setup-agent the user approved project defaults for missing fields",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow task-setup-agent to overwrite an existing input_task.yaml",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Return after one run instead of asking follow-up questions when defaults are not approved",
    )
    parser.add_argument("--max-turns", type=int, default=6, help="Maximum clarification rounds")
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
        help="Abort each run after this many seconds; 0 waits indefinitely.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = supramas_paths.workspace()
    paths = prepare_run_paths(repo_root, args.job_id, args.run_dir, args.overwrite)
    print(f"[stage0] run_dir: {paths.run_dir}", flush=True)
    print(f"[stage0] input_task: {paths.input_task}", flush=True)
    print(f"[stage0] session_archive_dir: {paths.logs_dir / 'dsh_sessions'}", flush=True)
    run_trace_id = generate_run_trace_id("stage0", paths.job_id)
    print(f"[stage0] run_trace_id: {run_trace_id}", flush=True)
    print("[stage0] waiting for task-setup-agent...", flush=True)

    prompt = build_task_setup_prompt(
        paths, args.research_goal, args.use_defaults, args.overwrite, run_trace_id
    )
    final_response = run_task_setup(
        prompt,
        repo_root=repo_root,
        input_task=paths.input_task,
        logs_dir=paths.logs_dir,
        interactive=not args.use_defaults and not args.non_interactive,
        max_turns=args.max_turns,
        model=args.model,
        provider=args.provider,
        permission_mode=args.permission_mode,
        timeout_seconds=args.timeout_seconds,
    )
    print(format_task_setup_response(final_response))
    if paths.input_task.exists():
        print(f"stage0 input task ready: {paths.input_task}")
    else:
        print(f"stage0 input task not written yet: {paths.input_task}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
