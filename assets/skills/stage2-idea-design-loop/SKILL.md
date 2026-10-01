---
name: stage2-idea-design-loop
description: Use when coordinating SupraMAS Stage 2 idea design from a Stage 1 strategy tree, idea state, candidate pool, review log, proximity graph, ranking, or final idea export.
---

# Stage 2 Idea Design Loop

Coordinate Stage 2 as a review-gated Co-Scientist style loop over a Stage 1 strategy tree.

## Inputs

- `runs/{job_id}/outputs/strategy_tree.json`, or `runs/{job_id}/tree_state.json` when the final Stage 1 export is unavailable.
- Optional user goals: target property, application scenario, lab constraints.

## Loop

```text
initialize idea_state
while not stop:
  idea-expert-agent creates candidates
  idea-review-agent reviews every new candidate
  idea-proximity-agent updates graph/clusters/diversity gaps
  idea-ranking-agent runs cluster-aware tournament ranking
  idea-evolution-agent creates new candidates from feedback
  evolved candidates return to idea-review-agent
export only review-accepted final ideas
```

## Hard Rules

- Final ideas must be review-accepted.
- Generated and evolved ideas must both pass review before ranking/final export.
- Stage 2 may write validation concepts, not full experimental protocols.
- Preserve Stage 1 provenance: `node_id`, `paper_id`, `record_id` or `limitation_id`, `chunk_id`, `evidence_text`.
- Write state after each loop boundary.
- Do not export placeholder validation text. A final idea must name the concrete evidence-derived route, composition/loading anchor, defect architecture, characterization/test conditions, and controls when these are present in Stage 1.
- Do not hide tuning decisions inside mechanism text. A final idea must include a separate `tuning_strategy` block with dominant dimensions, concrete Stage 1 strategy steps, integrated strategy, and controllable variables.
- If a required practical detail is absent from Stage 1 excerpts, the idea may include a clearly labeled `inferred_design` hypothesis. It must explain the Stage 1 evidence basis, physical rationale, uncertainty, and validation/control; otherwise route it to review/evolution for evidence strengthening.
- `final_idea_designs.md` must be researcher-readable Markdown only. Do not include fenced JSON blocks, raw JSON objects, schema dumps, or compact machine-readable summaries there; machine-readable content belongs in the JSON/JSONL files.

## Concrete Output Gate

Before final export, scan each candidate for:

- fabrication route: e.g. `MOCVD-grown REBCO with 7.5 at.% Zr`, `PLD YBCO + 5 mol.% BaZrO3 target`, `NdBCO/BZO sequential-ablation multilayer`;
- tuning strategy: Stage 1 `tuning_strategy` operations, not just dimension labels;
- design anchors: APC chemistry, loading, layer architecture, nanorod/nanodot geometry, growth temperature, field/temperature validation window;
- controls: named baseline from evidence, such as undoped REBCO, Zr-free REBCO, pure SmBCO, BZO-only nanorods, c-axis-only BZO, or formulation series;
- characterization/tests: methods and conditions appearing in evidence, such as TEM/SEM/EDS, torque magnetometry, Jc/Ic/Fp, 77 K/1 T, 4.2 K/5-45 T.

Reject or revise candidates whose validation concept only says that Stage 1 supports PLD/MOCVD/CSD/MOD/sputtering in general.

## Outputs

```text
runs/{job_id}/stage2/idea_state.json
runs/{job_id}/stage2/idea_pool.json
runs/{job_id}/stage2/idea_review_log.jsonl
runs/{job_id}/stage2/idea_similarity_graph.json
runs/{job_id}/stage2/idea_ranking.json
runs/{job_id}/stage2/final_idea_designs.md
```

Use `scripts/stage2_idea_design_codex.py --run-dir runs/{job_id}` for a real Codex SDK agent run. Do not use a deterministic local direct-generation runner for Stage 2 production output.
