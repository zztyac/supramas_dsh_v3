---
name: strategy-tree-validation
description: Review SupraMAS Stage 1 REBCO flux-pinning paper nodes and proposed edges for evidence grounding during tree construction.
---

# Strategy Tree Validation Skill

Review complete paper nodes and proposed edges before they are accepted into the strategy tree. A schema-valid node can still fail scientific validation if the evidence does not support the extracted claim or if the paper content was not persisted locally.

## Node Contract

Each paper node must represent one paper/article and contain:

- node_id
- level
- paper_id
- paper_title
- strategy_records
- limitation_records

Reject or flag:

- nodes that combine multiple papers,
- duplicate paper_id nodes,
- nodes with no strategy_records,
- nodes with paper metadata missing enough to prevent provenance.
- nodes whose source paper is not saved under `data/papers_parsed/`,
- nodes whose `evidence.chunk_id` cannot be resolved to saved local chunks,
- placeholder, abstract-only, or one-sentence nodes unless the task explicitly allows abstract-only evidence.

## Strategy Record Checks

Each strategy_record must contain:

- record_id
- tuning_dimension
- tuning_strategy
- tuning_effect
- evidence
- confidence

Check that:

- tuning_dimension is one of:
  - Composition tuning
  - Grain boundary tuning
  - Interface tuning
  - Texture tuning
  - Stress tuning
- tuning_strategy is a controllable method, not a vague goal.
- tuning_effect reports a material/defect/pinning/current effect.
- evidence supports the exact D/S/O claim.
- strategy_record does not contain limitation/expectation or deprecated outcome aliases.

## Limitation Record Checks

Each limitation_record must contain:

- limitation_id
- limitation
- expectation
- related_record_ids
- evidence
- confidence

Check that:

- limitation is grounded in paper text or explicitly downgraded to inferred.
- expectation follows logically from limitation.
- expectation is actionable for retrieval.
- related_record_ids refer only to strategy_records in the same paper.
- limitation_records are not duplicated.

## Scientific Plausibility Checks

Flag unsupported claims such as:

- APC addition improves Jc without any evidence of defect morphology or transport data.
- Strain/stress mechanism asserted without XRD/TEM/strain or lattice mismatch evidence.
- Isotropic pinning claimed from a c-axis-only result.
- Bulk result treated as directly applicable to coated conductors without transfer rationale.
- Numerical performance claims without source text.

## Edge Checks

When a parent context is provided, each builder-proposed edge must contain:

- parent_limitation_id
- edge_type: `direct`, `transferable`, or `exploratory`
- edge_rationale
- confidence

The coordinator adds `edge_id`, `parent_node_id`, `child_node_id`, and `parent_expectation` when assembling the final tree. Optional `child_record_id` and `child_tuning_effect` may be included only as annotations, not as required edge endpoints.

Allow open strategy fusion. The child paper does not need to directly satisfy every part of the parent expectation:

- `direct`: same or very close material/problem/mechanism, with evidence that directly addresses the expectation.
- `transferable`: adjacent REBCO/APC/process/defect/pinning strategy that plausibly transfers to the expectation.
- `exploratory`: broader but still domain-grounded analogy or strategy direction worth expanding, with low-to-moderate confidence.

Validate the edge by asking:

1. Does parent_limitation_id exist in parent node limitation_records?
2. Does child_node_id exist?
3. Does the referenced parent expectation match the parent limitation_record?
4. Is edge_type one of `direct`, `transferable`, or `exploratory`?
5. If child_record_id is provided, does it exist in child node strategy_records?
6. If child_tuning_effect is provided, does it match the optional child_record_id?
7. Is the child paper node at least domain-relevant to the parent expectation?
8. Is the edge more than keyword overlap, with an explicit mechanism, process, defect, morphology, measurement, or transfer bridge?
9. Is parent different from child and not a duplicate ancestor?

Reject only when the candidate is out of domain, has no evidence-supported strategy node, duplicates an ancestor, provides only keyword overlap with no bridge, or would mislead downstream tree expansion. If the relationship is useful but weak, request lower confidence or a weaker edge_type instead of rejecting.

## Output

Return a node-review artifact:

```json
{
  "review_scope": "node",
  "decision": "revise",
  "summary": "",
  "critical_issues": [],
  "minor_issues": [],
  "unsupported_claims": [],
  "evidence_corrections": [],
  "records_to_remove": [],
  "records_to_downgrade": [],
  "edge_issues": [],
  "questions_for_strategy_builder": [],
  "acceptance_conditions": []
}
```

Use `accept` only when no critical evidence, schema, or edge issue remains. Use `revise` for correctable issues and `reject` for unsupported, duplicate, or out-of-scope nodes.
