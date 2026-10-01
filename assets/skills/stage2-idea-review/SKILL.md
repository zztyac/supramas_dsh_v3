---
name: stage2-idea-review
description: Use when reviewing SupraMAS Stage 2 material design ideas for evidence grounding, superconducting physics plausibility, feasibility, novelty, and risk transparency.
---

# Stage 2 Idea Review

Review one candidate idea before it can enter proximity, ranking, or final export.

## Decision

Return exactly one:

- `accept`: evidence trace and material reasoning are adequate for Stage 2.
- `revise`: correctable gaps exist.
- `reject`: unsupported, duplicate, out of scope, or protocol-like.

## Checks

- Evidence trace resolves to Stage 1 node/record/chunk.
- Literature facts are separated from inferred design.
- REBCO / flux pinning mechanism is plausible.
- Claimed effects do not exceed evidence.
- Inferred numeric ratios, process windows, optimal regions, or performance targets are acceptable only when labeled `inferred_design` or `hypothesis`, separated from literature facts, and justified by evidence basis plus physical rationale. Papers, DOI, and chunk text must never be fabricated.
- The output stays at idea / validation-concept level, not full protocol.
- Validation concept is concrete: it identifies the actual or explicitly inferred route, composition/loading anchor or hypothesis, defect architecture, characterization/test conditions, and controls available from Stage 1 evidence.
- Tuning strategy is explicit: it includes dominant tuning dimensions, concrete Stage 1 `tuning_strategy` steps, integrated strategy, and controllable variables.
- Generic fallback wording is not acceptable. If the idea says only that PLD/MOCVD/CSD/MOD/sputtering are supported methods, or lists generic variables such as APC chemistry/concentration without values or source-specific anchors, return `revise`.
- If concrete details are missing from Stage 1 and no justified `inferred_design` hypothesis is provided, require `grounding_enhance` evolution or raw-paper evidence retrieval before final ranking.

## Required Review Questions

1. What exactly is being made: matrix, additive, site/defect type, and evidence-supported or clearly inferred loading?
2. How is it made at idea level: named source-paper route or clearly inferred route with evidence basis, not a menu of possible methods?
3. What is the tuning strategy: which dimensions, which concrete Stage 1 operations, which controllable variables, and how are they combined?
4. What will be compared: named control groups from evidence or a clearly inferred same-route baseline?
5. What will be measured: named characterization/performance tests with evidence-derived conditions when available?
6. What is new relative to the cited Stage 1 node rather than a restatement of the paper?

## Output

```json
{
  "idea_id": "",
  "decision": "revise",
  "summary": "",
  "critical_issues": [],
  "minor_issues": [],
  "unsupported_claims": [],
  "risk_notes": [],
  "acceptance_conditions": []
}
```
