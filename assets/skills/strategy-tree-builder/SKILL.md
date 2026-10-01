---
name: strategy-tree-builder
description: Use when recursively building a SupraMAS strategy tree from accepted paper nodes, limitations, expectations, builder/reviewer handoffs, frontier state, or Stage 1 tree artifacts.
---

# Strategy Tree Builder

Use this skill to turn reviewer-accepted strategy paper nodes into a recursive strategy tree.

This skill is not a literature search skill and not a strategy extraction skill. Its job is to define how `strategy-mining-agent` drives the recursive tree-building process by asking `strategy-builder-agent` to find related work that resolves a parent limitation, then asking `strategy-tree-reviewer` to verify the child node and edge.

## Core Semantics

Expansion is driven by limitation resolution:

```text
parent limitation_record
  -> limitation-resolution task for strategy-builder-agent
  -> one complete child paper node and optional proposed edge
  -> strategy-tree-reviewer evidence review
  -> accepted child node and edge
```

Accepted edges connect `parent limitation_record.expectation` to the child paper node. The child paper can be a `direct`, `transferable`, or `exploratory` response when the scientific bridge is explicit.

Do not reduce this to keyword or query generation. The builder task must describe what kind of work would resolve the limitation and what evidence is required.

## Limitation-Resolution Task

For each frontier `limitation_record`, create a task object:

```json
{
  "parent_node_id": "",
  "parent_limitation_id": "",
  "attempt_index": 1,
  "max_attempts": 3,
  "limitation": "",
  "expectation": "",
  "parent_context": {
    "paper_title": "",
    "related_strategy_records": []
  },
  "previous_attempts": [],
  "reviewer_acceptance_conditions": [],
  "builder_task": {
    "goal": "",
    "required_solution_type": [],
    "required_evidence": [],
    "reject_if": []
  }
}
```

Task-writing rules:

- `goal` asks `strategy-builder-agent` to find related work that can address, transfer toward, or explore the expectation derived from the limitation, not to search a bare query.
- `required_solution_type` names plausible strategy families, such as composition control, morphology control, processing-window optimization, interface/template engineering, strain relief, or mixed pinning landscapes.
- `required_evidence` states what must appear in the child paper, such as a controlled variable, defect morphology, pinning/Jc effect, and evidence for a direct, transferable, or exploratory bridge to the parent bottleneck.
- `reject_if` blocks false matches, such as generic APC papers, bulk-only papers, Jc-only improvements that ignore the limitation, or work with no evidence text.
- `attempt_index` and `max_attempts` come from `input_task.yaml` `expansion_policy`.
- `previous_attempts` lists rejected/no-edge papers and concise reasons so the builder does not repeat the same false match.
- `reviewer_acceptance_conditions` is populated after reviewer reject/revise and must be translated into required evidence and reject-if clauses for the next attempt.

Example:

```json
{
  "limitation": "Excessive second-phase addition degrades film crystallinity.",
  "expectation": "Increase pinning through controlled APC morphology or concentration while preserving epitaxial quality.",
  "builder_task": {
    "goal": "Find one REBCO thin-film study that addresses the APC concentration or morphology versus epitaxy trade-off and build it as a child strategy node.",
    "required_solution_type": ["composition control", "morphology control", "processing-window optimization", "interface/template engineering"],
    "required_evidence": ["APC concentration or morphology control", "pinning or Jc improvement", "preserved or measured crystallinity/epitaxy"],
    "reject_if": ["only mentions APCs without crystallinity evidence", "only improves Jc without addressing epitaxy", "bulk-only or non-transferable work"]
  }
}
```

## Recursive Build Loop

For each frontier limitation:

1. Create a limitation-resolution task.
2. Send that task plus parent context to `strategy-builder-agent`.
3. Receive one complete child paper node and optional proposed edge.
4. Send the child node and edge to `strategy-tree-reviewer`.
5. If reviewer returns `revise`, send `reviewer_feedback` back to `strategy-builder-agent`.
6. If reviewer returns `accept`, add the child node and edge to the tree.
7. If reviewer returns `reject`, record the reason. If attempts remain, create a new limitation-resolution task using reviewer `acceptance_conditions`; otherwise mark the limitation as `no_supported_child_after_attempt_budget`.
8. Add accepted child limitations to the frontier unless `max_depth` is reached or an explicit user-provided branch/child cap is reached.
9. Do not delete, skip, or coordinator-close a frontier because it looks duplicate, ancestor-like, weak, or not meaningful. Those are attempt-level outcomes. The frontier remains open until it receives an accepted edge, reaches a real cap, reaches `max_depth`, or exhausts its configured attempt budget.

## Mandatory Assembly Tool

Final tree export must be performed by `tools/assemble_strategy_tree.py`, not by hand-writing `strategy_tree.json`.

The coordinator must maintain a JSON build state with:

```json
{
  "tree": {
    "nodes": [],
    "edges": []
  },
  "frontier_status": [
    {
      "node_id": "N0",
      "limitation_id": "L1",
      "status": "accepted_edge",
      "attempts": []
    }
  ],
  "review_log": []
}
```

Run:

```bash
python tools/assemble_strategy_tree.py \
  --input-task runs/{job_id}/input_task.yaml \
  --state runs/{job_id}/outputs/tree_state.json
```

The assembly tool is the source of truth for `input_task.yaml` limits. It refuses export when:

- any node exceeds `tree_limits.max_depth`,
- any limitation on a node with `level < max_depth` lacks a terminal `frontier_status`,
- a limitation is marked `no_supported_child_after_attempt_budget` before `expansion_policy.max_child_attempts_per_limitation` attempts are recorded,
- `width_cap_reached` or `target_child_cap_reached` is used when the corresponding cap is `null` or not actually reached,
- `accepted_edge` has no matching edge to a child at `parent.level + 1`,
- an evidence `chunk_id` does not resolve under `corpus_path`,
- edge endpoints do not resolve to existing parent limitations and child paper nodes, or `edge_type` is not `direct`, `transferable`, or `exploratory`.

This prevents a coordinator from exporting a shallow tree simply because some first-level branches were accepted. If `max_depth=3`, every accepted level-1 child limitation must either be expanded to level 2, hit a real cap, or exhaust the configured child-attempt budget.

## Reviewer-Guided Retry

When a child edge is rejected, do not simply rerun the same query. Build the next attempt around what the reviewer said would make the edge acceptable.

For the next attempt:

- Put the rejected paper id and failure mode in `previous_attempts`.
- Copy reviewer `acceptance_conditions` into `reviewer_acceptance_conditions`.
- Add those conditions to `required_evidence`.
- Add a `reject_if` item that blocks the rejected mismatch pattern.

Example:

```json
{
  "parent_limitation_id": "L1",
  "attempt_index": 2,
  "max_attempts": 3,
  "previous_attempts": [
    {
      "paper_id": "arxiv_cond_mat_0310568_civale_angular_pinning_ybco",
      "decision": "reject",
      "reason": "Texture/defect-density engineering did not address BMO APC incorporation, Tc retention, or 77 K performance."
    }
  ],
  "reviewer_acceptance_conditions": [
    "Find a paper that explicitly studies Ba-metal-oxide APC incorporation and includes evidence relevant to Tc retention and 77 K performance."
  ],
  "builder_task": {
    "goal": "Find one REBCO thin-film study that addresses Sn/Hf/Ir-based BMO APC incorporation while preserving Tc and 77 K performance.",
    "required_solution_type": ["composition control", "morphology control", "processing-window optimization"],
    "required_evidence": ["BMO APC identity and concentration", "Tc or transition-temperature retention", "77 K Jc/pinning effect"],
    "reject_if": ["only discusses texture engineering", "does not include Tc evidence", "does not include 77 K performance evidence", "repeats rejected Civale texture-only paper"]
  }
}
```

## Stop Conditions

Stop expansion when:

- `max_depth` is reached,
- `max_branch_per_node` is a number and is reached for a parent,
- `target_child_nodes` is a number and is reached globally,
- `max_child_attempts_per_limitation` is reached without reviewer acceptance,
- no reviewer-accepted child can resolve the limitation after the configured attempt budget is exhausted.

Do not stop a frontier directly because a candidate child paper is already an ancestor or duplicate, evidence is too weak, or a candidate does not produce a meaningful resolution task. Record that as an attempt outcome and continue until the frontier receives an accepted edge or exhausts its configured attempt budget.

By default, `max_branch_per_node` and `target_child_nodes` are `null`, meaning unbounded. Do not impose hidden width limits when these fields are `null`.
