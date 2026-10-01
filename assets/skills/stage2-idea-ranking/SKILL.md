---
name: stage2-idea-ranking
description: Use when ranking reviewed Stage 2 material ideas, running pairwise tournament comparisons, preserving cluster diversity, or producing winner/loser rationales.
---

# Stage 2 Idea Ranking

Rank only reviewed ideas. Final selected ideas must be review-accepted.

## Ranking Criteria

- Evidence grounding, including concrete fabrication route, composition/loading, defect architecture, tests, and controls.
- Novelty relative to Stage 1 papers.
- Expected impact on flux pinning, in-field Jc, Ic, or Fp.
- Materials plausibility.
- Idea-level testability.
- Feasibility and risk transparency.
- Diversity contribution from proximity graph.

## Scoring Guidance

Prefer ideas that:

- combine at least two evidence-backed tuning dimensions without losing a concrete material recipe;
- preserve source-paper anchors such as `7.5 at.% Zr`, `5 mol.% BaZrO3`, `2 vol% BZO`, `15% BZO`, `800/860/920 degC`, `77 K/1 T`, or `4.2 K/5-45 T`;
- have explicit controls that make the hypothesis falsifiable;
- state risks tied to the actual mechanism, such as Tc suppression from high APC loading, texture degradation, flux jumps in thick/high-current tapes, or ambiguous attribution between correlated and random pinning.

Downgrade ideas that are scientifically plausible but still read like a template, lack concrete validation anchors, or merely restate a Stage 1 paper without a new design move.

## Tournament Rules

- Compare similar ideas within clusters first.
- Keep one or more strong representatives from distinct clusters.
- Record winner/loser rationale.
- Send loss patterns to `idea-evolution-agent`.
- Never rank an unreviewed or review-revise idea above an accepted one.

## Output

```json
{
  "ranking_round": 1,
  "pairwise_matches": [],
  "ranked_ideas": [],
  "ranking_feedback_for_evolution": []
}
```
