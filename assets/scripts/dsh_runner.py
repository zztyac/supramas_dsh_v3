#!/usr/bin/env python3
"""Run SupraMAS stages on DeepSeek Harness from Python.

This replaces the `openai_codex` SDK bridge used before the migration. It shells
out to `dsh --profile headless --json`, parses the line-delimited JSON event
stream, archives the session transcript, and reports the final answer plus the
exit status.

Design notes that matter:

* The task is passed as a positional argument, so the prompt is never spliced
  into a shell string.
* We never pass `--session-id` for a new run. DeepSeek Harness only adopts a
  session that already exists, so the id is read back from the leading `session`
  event instead.
* `--json` is a lossy projection (8 KiB per key, 32 KiB per line). The archived
  session log under `~/.dsh/sessions/` is the lossless record.
* Run resumption is driven by `runs/{job_id}/tree_state.json`, not by session
  adoption.

Usage:
    python scripts/dsh_runner.py --dry-run --prompt "hello"
    python scripts/dsh_runner.py --prompt "hello" --events-out /tmp/events.jsonl
    python scripts/dsh_runner.py --self-check
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:  # imported as `scripts.dsh_runner`
    from scripts import supramas_paths
except ImportError:  # imported as a top-level module
    import supramas_paths  # type: ignore[no-redef]

# `ASSET_ROOT` is where the SupraMAS installation lives (tools/, schemas/, role
# contracts, bundle patch); `WORKSPACE` is the caller's project, where runs/ go.
# In a source checkout both are the repository root; an installed bundle puts its
# assets under a profile's node_modules/, so the two must stay separate.
ASSET_ROOT = supramas_paths.asset_root()
DEFAULT_PATCH = supramas_paths.bundle_patch()
DEFAULT_PROFILE = "headless"

# Kept for callers and tests that referenced the old single-root constant.
REPO_ROOT = ASSET_ROOT

# Where the DeepSeek Harness desktop app keeps its CLI launcher on macOS.
MACOS_LAUNCHER = Path(
    "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"
)

PERMISSION_MODES = ("read-only", "workspace-write", "danger-full-access")


def _resolve_patch(patch: Path | str | None) -> Path | None:
    """Resolve a patch reference to an absolute path, or None."""
    if not patch:
        return None
    candidate = Path(patch)
    if candidate.is_absolute():
        return candidate
    for base in (Path.cwd(), ASSET_ROOT, ASSET_ROOT.parent):
        resolved = base / candidate
        if resolved.is_file():
            return resolved.resolve()
    return (ASSET_ROOT / candidate).resolve()


def find_dsh() -> str:
    """Locate the `dsh` launcher: $DSH_BIN, then PATH, then the macOS app bundle."""
    override = os.environ.get("DSH_BIN")
    if override:
        return override
    found = shutil.which("dsh")
    if found:
        return found
    if MACOS_LAUNCHER.is_file():
        return str(MACOS_LAUNCHER)
    raise FileNotFoundError(
        "dsh launcher not found. Install the DeepSeek Harness command line tool, "
        "put `dsh` on PATH, or set DSH_BIN to the launcher path."
    )


def session_slug(workspace: Path) -> str:
    """Mirror the workspace directory name DeepSeek Harness uses under ~/.dsh/sessions.

    Derived from observed directories, not a documented contract:

        /Users/zzz/Desktop/SupraMAS_V2  ->  --Users-zzz-Desktop-SupraMAS_V2--

    `archive_session` always falls back to a search, so a change in this
    formatting degrades to a slower lookup rather than a wrong answer.
    """
    return "-" + str(workspace).replace("/", "-") + "--"


def sessions_root(workspace: Path) -> Path:
    home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    return home / "sessions" / session_slug(workspace)


@dataclass(frozen=True)
class SessionInfo:
    """One persisted DeepSeek Harness session, including subagent sessions.

    Subagent sessions live in the *same* workspace directory as their parent and
    are named with a bare UUID rather than `session-<uuid>`, so a single-directory
    copy silently loses them. The authoritative link is the `parentSession` field
    in the first record of the session log.
    """

    session_id: str
    directory: Path
    parent_session: str | None = None
    delegation_depth: int = 0
    origin: str | None = None

    @property
    def is_subagent(self) -> bool:
        return bool(self.parent_session)


def read_session_header(log_path: Path) -> dict | None:
    """Read the header record of a session log (Zstandard-compressed JSONL).

    Uses the stdlib `compression.zstd` module available in Python 3.14+, so this
    needs no third-party dependency.
    """
    try:
        from compression import zstd  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        raw = zstd.decompress(log_path.read_bytes())
    except Exception:
        return None
    first = raw.split(b"\n", 1)[0]
    try:
        header = json.loads(first)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return header if isinstance(header, dict) else None


def list_sessions(workspace: Path) -> list[SessionInfo]:
    """Describe every session persisted for a workspace."""
    root = sessions_root(workspace)
    if not root.is_dir():
        return []
    sessions: list[SessionInfo] = []
    for directory in sorted(root.iterdir()):
        log = directory / "session.v4.jsonl.zstd"
        if not log.is_file():
            continue
        header = read_session_header(log) or {}
        session_id = header.get("id") or directory.name
        try:
            depth = int(header.get("delegationDepth") or 0)
        except (TypeError, ValueError):
            depth = 0
        sessions.append(
            SessionInfo(
                session_id=str(session_id),
                directory=directory,
                parent_session=header.get("parentSession"),
                delegation_depth=depth,
                origin=header.get("origin"),
            )
        )
    return sessions


def session_tree(workspace: Path, root_session_id: str) -> list[SessionInfo]:
    """Return the root session followed by every subagent session beneath it."""
    sessions = list_sessions(workspace)
    by_id = {session.session_id: session for session in sessions}
    children: dict[str, list[SessionInfo]] = {}
    for session in sessions:
        if session.parent_session:
            children.setdefault(session.parent_session, []).append(session)

    tree: list[SessionInfo] = []
    root = by_id.get(root_session_id)
    if root is not None:
        tree.append(root)

    queue = [root_session_id]
    seen = {root_session_id}
    while queue:
        parent = queue.pop(0)
        for child in children.get(parent, []):
            if child.session_id in seen:
                continue
            seen.add(child.session_id)
            tree.append(child)
            queue.append(child.session_id)
    return tree


@dataclass
class DshRunResult:
    """Outcome of one DeepSeek Harness headless run."""

    exit_code: int
    final_text: str
    session_id: str | None
    events: list[dict] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    stderr: str = ""
    events_path: Path | None = None
    session_archive: Path | None = None
    session_archives: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def summary(self) -> str:
        lines = [
            f"exit_code: {self.exit_code}",
            f"session_id: {self.session_id or '<none>'}",
            f"events: {len(self.events)}",
            f"final_text: {len(self.final_text)} chars",
        ]
        if self.events_path:
            lines.append(f"events_path: {self.events_path}")
        if self.session_archives:
            lines.append(f"session_archive: {self.session_archive} ({len(self.session_archives)} session(s))")
        elif self.session_archive:
            lines.append(f"session_archive: {self.session_archive}")
        if self.stderr.strip():
            lines.append("stderr (tail):")
            lines.extend(f"  {line}" for line in self.stderr.strip().splitlines()[-5:])
        return "\n".join(lines)


class DshRunner:
    """Build and execute `dsh --profile <profile> --json <task>` invocations."""

    def __init__(
        self,
        repo_root: Path | None = None,
        profile: str = DEFAULT_PROFILE,
        patch: Path | str | None = DEFAULT_PATCH,
        permission_mode: str | None = None,
        dsh_bin: str | None = None,
        extra_args: list[str] | None = None,
        model: str | None = None,
        provider: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve() if repo_root else supramas_paths.workspace()
        self.profile = profile
        # A relative patch resolves against the asset root, so callers may keep
        # naming it by its source-checkout path.
        self.patch = _resolve_patch(patch)
        if permission_mode and permission_mode not in PERMISSION_MODES:
            raise ValueError(
                f"permission_mode must be one of {PERMISSION_MODES}, got {permission_mode!r}"
            )
        self.permission_mode = permission_mode
        self.dsh_bin = dsh_bin
        self.extra_args = list(extra_args or [])
        self.model = model
        self.provider = provider
        self.reasoning_effort = reasoning_effort
        self._temp_patches: list[Path] = []
        self._cleaned = False

    def model_patch_path(self) -> Path | None:
        """Materialize a `agent-default-model` override patch when a model was requested.

        `dsh headless` reads its model from the profile, not from a flag, so an
        override has to arrive as an extra `--patch` layer applied after the bundle.
        """
        if not self.model:
            return None
        if self._temp_patches:
            return self._temp_patches[0]
        if getattr(self, "_cleaned", False):
            # cleanup() already ran; do not leave another temp file behind.
            return None
        lines = [
            "# GENERATED by scripts/dsh_runner.py -- model override layer.",
            "- id: agent-default-model",
            "  config:",
        ]
        if self.provider:
            lines.append(f"    provider: {self.provider}")
        lines.append(f"    model: {self.model}")
        if self.reasoning_effort:
            lines.append(f"    reasoningEffort: {self.reasoning_effort}")
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".model-patch.yml", delete=False, encoding="utf-8"
        )
        handle.write("\n".join(lines) + "\n")
        handle.close()
        path = Path(handle.name)
        self._temp_patches.append(path)
        return path

    def cleanup(self) -> None:
        """Remove any temporary patch files this runner created."""
        for path in self._temp_patches:
            try:
                path.unlink()
            except OSError:
                pass
        self._temp_patches.clear()
        self._cleaned = True

    def __enter__(self) -> "DshRunner":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cleanup()

    def build_command(self, prompt: str, *, json_events: bool = True) -> list[str]:
        """Return the argv for one run. The prompt is a positional argument."""
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        command = [self.dsh_bin or find_dsh(), "--profile", self.profile]
        if self.patch:
            command += ["--patch", str(self.patch)]
        model_patch = self.model_patch_path()
        if model_patch:
            command += ["--patch", str(model_patch)]
        command += list(self.extra_args)
        if json_events:
            command.append("--json")
        command.append(prompt)
        return command

    def build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.permission_mode:
            env["DSH_PERMISSION_MODE"] = self.permission_mode
        return env

    def run(
        self,
        prompt: str,
        *,
        events_out: Path | None = None,
        archive_session_to: Path | None = None,
        timeout_seconds: float = 0,
    ) -> DshRunResult:
        """Run one task and collect its events, final answer, and exit status."""
        command = self.build_command(prompt)

        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                env=self.build_env(),
                capture_output=True,
                text=True,
                timeout=timeout_seconds or None,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return DshRunResult(
                exit_code=124,
                final_text="",
                session_id=None,
                command=command,
                stderr=f"timed out after {timeout_seconds:g}s\n{exc.stderr or ''}",
            )

        events: list[dict] = []
        session_id: str | None = None
        final_text = ""
        for line in completed.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(event)
            kind = event.get("type")
            if kind == "session" and session_id is None:
                session_id = event.get("sessionId") or event.get("session_id")
            elif kind == "final":
                final_text = event.get("text", "") or final_text

        if not final_text and not events:
            # Non-JSON fallback: the runner prints the answer to stdout directly.
            final_text = completed.stdout.strip()

        if events_out is not None:
            events_out.parent.mkdir(parents=True, exist_ok=True)
            with events_out.open("w", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")

        archives: list[Path] = []
        if archive_session_to is not None and session_id:
            archives = self.archive_session_tree(session_id, archive_session_to)

        return DshRunResult(
            exit_code=completed.returncode,
            final_text=final_text,
            session_id=session_id,
            events=events,
            command=command,
            stderr=completed.stderr,
            events_path=events_out,
            session_archive=archives[0] if archives else None,
            session_archives=archives,
        )

    def archive_session(self, session_id: str, destination: Path) -> Path | None:
        """Copy one persisted session directory for `session_id` under `destination`."""
        return self._copy_session_dir(self._locate_session_dir(session_id), session_id, destination)

    def archive_session_tree(self, session_id: str, destination: Path) -> list[Path]:
        """Copy the session and every subagent session beneath it.

        A stage run spawns builder/reviewer subagents whose sessions are siblings of
        the parent session, not children of it on disk. Copying only the parent would
        drop exactly the transcripts that matter for auditing a strategy-tree run, so
        the tree is resolved through each log's `parentSession` field.
        """
        destination = Path(destination)
        archived: list[Path] = []
        for info in session_tree(self.repo_root, session_id):
            copied = self._copy_session_dir(info.directory, info.session_id, destination)
            if copied is not None:
                archived.append(copied)
        if archived:
            return archived
        # Session tree discovery can miss sessions written without a readable
        # header; fall back to the parent directory itself.
        fallback = self.archive_session(session_id, destination)
        return [fallback] if fallback else []

    def _locate_session_dir(self, session_id: str) -> Path | None:
        source = sessions_root(self.repo_root) / session_id
        if source.is_dir():
            return source
        # Fall back to a search: the slug format is not a documented contract.
        sessions = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh")) / "sessions"
        candidates = list(sessions.glob(f"*/{session_id}"))
        return candidates[0] if candidates else None

    @staticmethod
    def _copy_session_dir(source: Path | None, session_id: str, destination: Path) -> Path | None:
        if source is None or not source.is_dir():
            return None
        target = Path(destination) / session_id
        shutil.copytree(source, target, dirs_exist_ok=True)
        return target


def require_output_files(output_dir: Path, names: tuple[str, ...], final_text: str) -> None:
    """Fail loudly when a run reported success but did not produce every artifact."""
    missing = [name for name in names if not (output_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            "\n".join(
                [
                    f"missing output file(s) in {output_dir}: {', '.join(missing)}",
                    "",
                    "The run exited successfully but did not produce every required artifact.",
                    "",
                    "Last agent response:",
                    final_text.strip() or "<empty response>",
                ]
            )
        )


def self_check() -> int:
    """Report the resolved launcher, patch, and skill root without running an agent."""
    problems: list[str] = []
    try:
        launcher = find_dsh()
        print(f"launcher:      {launcher}")
    except FileNotFoundError as exc:
        problems.append(str(exc))
        print(f"launcher:      MISSING ({exc})")

    print(f"asset root:    {ASSET_ROOT}")

    patch_path = DEFAULT_PATCH
    print(f"bundle patch:  {patch_path} {'ok' if patch_path.is_file() else 'MISSING'}")
    if not patch_path.is_file():
        problems.append(f"bundle patch not found: {patch_path}")

    # Two skill roots are legitimate: the checked-out tree links them into
    # .dsh/skills, while an installed bundle ships them under assets/skills and
    # registers them through lib/index.js.
    linked_dir = ASSET_ROOT / ".dsh" / "skills"
    linked = sorted(p.name for p in linked_dir.iterdir()) if linked_dir.is_dir() else []
    bundled = supramas_paths.skills_dir()
    bundled_count = len(list(bundled.glob("*/SKILL.md"))) if bundled else 0
    if linked:
        print(f"skill root:    {linked_dir} ({len(linked)} linked)")
    elif bundled_count:
        print(f"skill root:    bundled at {bundled} ({bundled_count} skills, via lib/index.js)")
    else:
        problems.append("no skills found; run scripts/link_skills.sh or rebuild the bundle")

    agents_dir = supramas_paths.agents_dir()
    contracts = sorted(p.stem for p in agents_dir.glob("*.md")) if agents_dir.is_dir() else []
    print(f"role contracts:{len(contracts)} under {agents_dir}")
    if not contracts:
        problems.append(f"no role contracts under {agents_dir}")

    print(f"workspace:     {supramas_paths.workspace()}")
    print(f"session root:  {sessions_root(supramas_paths.workspace())}")
    print(f"permission:    {os.environ.get('DSH_PERMISSION_MODE', 'workspace-write (default)')}")

    if problems:
        print("\nproblems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nself-check: ok")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a SupraMAS task on DeepSeek Harness through the headless profile."
    )
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", help="Task text to send.")
    prompt_group.add_argument("--prompt-file", type=Path, help="Read the task text from a file.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="DeepSeek Harness profile name.")
    parser.add_argument(
        "--patch",
        default=DEFAULT_PATCH,
        help="Bundle patch to overlay (absolute, or relative to the asset root).",
    )
    parser.add_argument(
        "--repo-root",
        "--workspace",
        dest="repo_root",
        type=Path,
        default=None,
        help="Working directory for the run; runs/ is written here. Defaults to $PWD.",
    )
    parser.add_argument(
        "--permission-mode",
        choices=PERMISSION_MODES,
        help="Sets DSH_PERMISSION_MODE. Unattended runs should not rely on the approval default.",
    )
    parser.add_argument("--events-out", type=Path, help="Write the JSON event stream here.")
    parser.add_argument("--archive-session-to", type=Path, help="Copy the session transcript here.")
    parser.add_argument(
        "--provider",
        help=(
            "Override the profile's agent-default-model provider. A profile's default "
            "provider may have no credentials on this machine; the desktop profile uses "
            "'deepseek-account' while the headless template defaults to 'deepseek-official'."
        ),
    )
    parser.add_argument("--model", help="Override the profile's agent-default-model model id.")
    parser.add_argument(
        "--reasoning-effort", help="Reasoning effort for the model override (e.g. high)."
    )
    parser.add_argument("--timeout-seconds", type=float, default=0, help="0 waits indefinitely.")
    parser.add_argument("--dry-run", action="store_true", help="Print the command and exit.")
    parser.add_argument("--self-check", action="store_true", help="Report local wiring and exit.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.self_check:
        return self_check()

    if args.prompt_file:
        prompt = args.prompt_file.read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    elif args.dry_run:
        prompt = "<task>"
    else:
        print("provide --prompt, --prompt-file, or --self-check", file=sys.stderr)
        return 2

    runner = DshRunner(
        repo_root=args.repo_root,
        profile=args.profile,
        patch=args.patch,
        permission_mode=args.permission_mode,
        model=args.model,
        provider=args.provider,
        reasoning_effort=args.reasoning_effort,
    )
    try:
        if args.dry_run:
            command = runner.build_command(prompt)
            print(" ".join(command))
            env = runner.build_env()
            if env.get("DSH_PERMISSION_MODE"):
                print(f"DSH_PERMISSION_MODE={env['DSH_PERMISSION_MODE']}")
            return 0

        result = runner.run(
            prompt,
            events_out=args.events_out,
            archive_session_to=args.archive_session_to,
            timeout_seconds=args.timeout_seconds,
        )
    finally:
        runner.cleanup()

    print(result.summary(), file=sys.stderr)
    if result.final_text:
        print(result.final_text)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
