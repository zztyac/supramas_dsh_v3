from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {
    "accepted_edge",
    "no_supported_child_after_attempt_budget",
    "depth_limit_reached",
    "width_cap_reached",
    "target_child_cap_reached",
}

EDGE_TYPES = {"direct", "transferable", "exploratory"}


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        return data
    except ModuleNotFoundError:
        return load_simple_yaml(path)


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Small YAML subset parser for this repo's input_task.yaml shape."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending_key: tuple[int, dict[str, Any], str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            if pending_key and pending_key[0] == indent - 2:
                _, mapping, key = pending_key
                if not isinstance(mapping.get(key), list):
                    mapping[key] = []
                stack.append((indent - 2, mapping[key]))
                parent = mapping[key]
                pending_key = None
            if not isinstance(parent, list):
                raise ValueError(f"Unsupported YAML list placement in {path}: {raw_line}")
            parent.append(parse_scalar(line[2:]))
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not isinstance(parent, dict):
            raise ValueError(f"Unsupported YAML mapping placement in {path}: {raw_line}")
        if raw_value:
            parent[key] = parse_scalar(raw_value)
            pending_key = None
        else:
            parent[key] = {}
            pending_key = (indent, parent, key)
            stack.append((indent, parent[key]))
    return root


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def state_tree(state: dict[str, Any]) -> dict[str, Any]:
    tree = state.get("tree", state)
    if not isinstance(tree, dict):
        raise ValueError("state.tree must be an object")
    for key in ("nodes", "edges"):
        if not isinstance(tree.get(key), list):
            raise ValueError(f"state tree must contain list field {key}")
    return tree


def frontier_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries = state.get("frontier_status", state.get("frontier", []))
    if not isinstance(entries, list):
        raise ValueError("state.frontier_status must be a list")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each frontier_status entry must be an object")
    return entries


def child_count(tree: dict[str, Any]) -> int:
    return sum(1 for node in tree["nodes"] if node.get("level", 0) > 0)


def fail(errors: list[str]) -> None:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    raise SystemExit(1)


def validate_frontier_closure(task: dict[str, Any], state: dict[str, Any]) -> None:
    tree = state_tree(state)
    frontier = frontier_entries(state)
    tree_limits = task.get("tree_limits") or {}
    expansion_policy = task.get("expansion_policy") or {}
    max_depth = tree_limits.get("max_depth")
    if not isinstance(max_depth, int):
        raise ValueError("input_task.yaml tree_limits.max_depth must be an integer")
    max_attempts = expansion_policy.get("max_child_attempts_per_limitation", 3)
    if not isinstance(max_attempts, int):
        raise ValueError("input_task.yaml expansion_policy.max_child_attempts_per_limitation must be an integer")

    max_branch_per_node = tree_limits.get("max_branch_per_node")
    target_root_nodes = tree_limits.get("target_root_nodes")
    target_child_nodes = tree_limits.get("target_child_nodes")

    errors: list[str] = []
    nodes = {node["node_id"]: node for node in tree["nodes"]}
    edges = tree["edges"]
    outgoing_by_parent_limitation: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    outgoing_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        key = (edge["parent_node_id"], edge["parent_limitation_id"])
        outgoing_by_parent_limitation[key].append(edge)
        outgoing_by_parent[edge["parent_node_id"]].append(edge)

    root_nodes = [node for node in tree["nodes"] if node.get("level") == 0]
    if isinstance(target_root_nodes, int) and len(root_nodes) != target_root_nodes:
        errors.append(f"target_root_nodes={target_root_nodes}, but tree has {len(root_nodes)} root nodes")

    if isinstance(target_child_nodes, int) and child_count(tree) > target_child_nodes:
        errors.append(f"target_child_nodes={target_child_nodes}, but tree has {child_count(tree)} child nodes")

    if isinstance(max_branch_per_node, int):
        for node_id, node_edges in outgoing_by_parent.items():
            if len(node_edges) > max_branch_per_node:
                errors.append(
                    f"node {node_id} has {len(node_edges)} outgoing edges, exceeding max_branch_per_node={max_branch_per_node}"
                )

    frontier_by_key = {(entry.get("node_id"), entry.get("limitation_id")): entry for entry in frontier}

    for node in tree["nodes"]:
        node_id = node["node_id"]
        level = node["level"]
        if level > max_depth:
            errors.append(f"node {node_id} level={level} exceeds max_depth={max_depth}")
            continue
        if level == max_depth:
            continue
        for limitation in node.get("limitation_records", []):
            limitation_id = limitation["limitation_id"]
            key = (node_id, limitation_id)
            entry = frontier_by_key.get(key)
            if entry is None:
                errors.append(
                    f"frontier {node_id}.{limitation_id} is missing status; cannot export before max_depth={max_depth}"
                )
                continue
            status = entry.get("status")
            if status not in TERMINAL_STATUSES:
                errors.append(f"frontier {node_id}.{limitation_id} has non-terminal or invalid status {status!r}")
                continue
            linked_edges = outgoing_by_parent_limitation.get(key, [])
            if status == "accepted_edge":
                if not linked_edges:
                    errors.append(f"frontier {node_id}.{limitation_id} status accepted_edge but no outgoing edge exists")
                    continue
                for edge in linked_edges:
                    child = nodes.get(edge["child_node_id"])
                    if child is None:
                        errors.append(f"edge {edge.get('edge_id')} points to missing child node {edge['child_node_id']}")
                    elif child["level"] != level + 1:
                        errors.append(
                            f"edge {edge.get('edge_id')} child {child['node_id']} level={child['level']} "
                            f"but expected {level + 1}"
                        )
            elif linked_edges:
                errors.append(f"frontier {node_id}.{limitation_id} status {status} but outgoing edge exists")
            elif status == "no_supported_child_after_attempt_budget":
                attempts = entry.get("attempts", [])
                if not isinstance(attempts, list) or len(attempts) < max_attempts:
                    errors.append(
                        f"frontier {node_id}.{limitation_id} exhausted without edge but has "
                        f"{len(attempts) if isinstance(attempts, list) else 0} attempts; expected >= {max_attempts}"
                    )
            elif status == "depth_limit_reached":
                errors.append(f"frontier {node_id}.{limitation_id} cannot be depth_limit_reached at level {level} < {max_depth}")
            elif status == "width_cap_reached" and max_branch_per_node is None:
                errors.append(f"frontier {node_id}.{limitation_id} says width_cap_reached but max_branch_per_node is null")
            elif status == "target_child_cap_reached":
                if target_child_nodes is None:
                    errors.append(f"frontier {node_id}.{limitation_id} says target_child_cap_reached but target_child_nodes is null")
                elif child_count(tree) < target_child_nodes:
                    errors.append(
                        f"frontier {node_id}.{limitation_id} says target_child_cap_reached but child_count={child_count(tree)} "
                        f"< target_child_nodes={target_child_nodes}"
                    )
    if errors:
        fail(errors)


def validate_edges(tree: dict[str, Any]) -> None:
    errors: list[str] = []
    nodes = {node["node_id"]: node for node in tree["nodes"]}
    for edge in tree["edges"]:
        parent = nodes.get(edge["parent_node_id"])
        child = nodes.get(edge["child_node_id"])
        if parent is None:
            errors.append(f"edge {edge.get('edge_id')} parent node is missing")
            continue
        if child is None:
            errors.append(f"edge {edge.get('edge_id')} child node is missing")
            continue
        if edge.get("edge_type") not in EDGE_TYPES:
            errors.append(
                f"edge {edge.get('edge_id')} edge_type must be one of {sorted(EDGE_TYPES)}"
            )
        parent_limits = {lim["limitation_id"]: lim for lim in parent.get("limitation_records", [])}
        parent_limit = parent_limits.get(edge["parent_limitation_id"])
        if parent_limit is None:
            errors.append(f"edge {edge.get('edge_id')} parent limitation is missing")
        elif "parent_expectation" not in edge:
            errors.append(f"edge {edge.get('edge_id')} parent expectation is missing")
        elif edge["parent_expectation"] != parent_limit.get("expectation"):
            errors.append(f"edge {edge.get('edge_id')} parent expectation does not match limitation record")
        child_record_id = edge.get("child_record_id")
        if child_record_id is not None:
            child_records = {rec["record_id"]: rec for rec in child.get("strategy_records", [])}
            child_record = child_records.get(child_record_id)
            if child_record is None:
                errors.append(f"edge {edge.get('edge_id')} child strategy record is missing")
            elif "child_tuning_effect" in edge and edge["child_tuning_effect"] != child_record.get("tuning_effect"):
                errors.append(f"edge {edge.get('edge_id')} child tuning effect does not match strategy record")
    if errors:
        fail(errors)


def resolve_relative_path(path_value: Any, input_task_path: Path) -> Path:
    path = Path(str(path_value))
    if path.is_absolute() or path.exists():
        return path
    task_relative = input_task_path.parent / path
    if task_relative.exists():
        return task_relative
    return path


def evidence_store_path(task: dict[str, Any], input_task_path: Path) -> Path:
    papers_dir = task.get("papers_dir")
    if not papers_dir:
        raise ValueError("input_task.yaml papers_dir is required")
    return resolve_relative_path(papers_dir, input_task_path)


def validate_evidence_chunks(tree: dict[str, Any], store_path: Path) -> None:
    errors: list[str] = []
    for node in tree["nodes"]:
        paper_file = store_path / f"{node['paper_id']}.json"
        if not paper_file.exists():
            errors.append(f"paper file missing for {node['node_id']}: {paper_file}")
            continue
        paper = load_json(paper_file)
        chunk_ids = {chunk.get("chunk_id") for chunk in paper.get("chunks", []) if isinstance(chunk, dict)}
        for group_name in ("strategy_records", "limitation_records"):
            for record in node.get(group_name, []):
                evidence = record.get("evidence", {})
                chunk_id = evidence.get("chunk_id")
                record_id = record.get("record_id", record.get("limitation_id"))
                if chunk_id not in chunk_ids:
                    errors.append(f"{node['node_id']}.{record_id} evidence chunk {chunk_id!r} not found in {paper_file}")
    if errors:
        fail(errors)


def render_review_report(task: dict[str, Any], state: dict[str, Any]) -> str:
    tree = state_tree(state)
    frontier = frontier_entries(state)
    lines = [
        "# Stage 1 Assembly Report",
        "",
        f"- Job ID: `{task['job_id']}`",
        f"- Research topic: {task['research_topic']}",
        f"- max_depth: `{task['tree_limits']['max_depth']}`",
        f"- max_child_attempts_per_limitation: `{task['expansion_policy'].get('max_child_attempts_per_limitation', 3)}`",
        f"- Exported nodes: `{len(tree['nodes'])}`",
        f"- Exported edges: `{len(tree['edges'])}`",
        "",
        "## Frontier Status",
        "",
    ]
    for entry in frontier:
        node_id = entry.get("node_id")
        limitation_id = entry.get("limitation_id")
        status = entry.get("status")
        reason = entry.get("reason", "")
        suffix = f" - {reason}" if reason else ""
        lines.append(f"- `{node_id}.{limitation_id}`: `{status}`{suffix}")
    lines.append("")
    return "\n".join(lines)


def write_outputs(task: dict[str, Any], state: dict[str, Any], output_dir: Path) -> None:
    tree = dict(state_tree(state))
    tree["job_id"] = task["job_id"]
    tree["research_topic"] = task["research_topic"]
    if "material_scope" in task:
        tree["material_scope"] = task["material_scope"]
    if "target_property" in task:
        tree["target_property"] = task["target_property"]

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "strategy_tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    review_log = state.get("review_log", [])
    if not isinstance(review_log, list):
        raise ValueError("state.review_log must be a list when provided")
    with (output_dir / "node_review_log.jsonl").open("w", encoding="utf-8") as handle:
        for item in review_log:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    report = state.get("review_report")
    if not isinstance(report, str):
        report = render_review_report(task, state)
    (output_dir / "review_report.md").write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble a SupraMAS strategy tree only when input_task.yaml frontier/depth constraints are satisfied."
    )
    parser.add_argument("--input-task", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True, help="JSON state with tree, frontier_status, and optional review_log")
    parser.add_argument("--output-dir", type=Path, help="Override input_task.yaml output_dir")
    parser.add_argument("--check-only", action="store_true", help="Validate constraints without writing outputs")
    args = parser.parse_args()

    task = load_yaml(args.input_task)
    state = load_json(args.state)
    tree = state_tree(state)
    validate_edges(tree)
    validate_frontier_closure(task, state)
    validate_evidence_chunks(tree, evidence_store_path(task, args.input_task))

    if not args.check_only:
        output_dir = args.output_dir or Path(task["output_dir"])
        write_outputs(task, state, output_dir)
        print(f"assembled: {output_dir / 'strategy_tree.json'}")
    else:
        print("valid assembly state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
