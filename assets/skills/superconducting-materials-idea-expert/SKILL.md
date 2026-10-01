---
name: superconducting-materials-idea-expert
description: Use when generating Stage 2 superconducting materials design ideas from REBCO strategy tree records, limitations, expectations, and evidence traces.
---

# Superconducting Materials Idea Expert

Generate candidate material-design ideas from Stage 1 evidence. This is not free brainstorming.

## Required Idea Fields

Use the 15-field material research idea template:

```text
1. Idea 标题
2. 材料体系
3. 目标性能
4. 应用场景
5. 科学问题
6. 核心假设
7. 材料设计方案
8. 调控策略
9. 机理路径
10. 文献依据
11. 预期结果
12. 实验验证方案
13. 风险分析
14. 可行性评价
15. 创新性评价
```

## Evidence Use

- Use Stage 1 `strategy_records` for design ingredients.
- Use Stage 1 `limitation_records[].expectation` for motivation.
- Every major claim needs `node_id`, `record_id` or `limitation_id`, `chunk_id`, and evidence text.
- Mark each claim as `evidence_supported`, `inferred_design`, or `speculative_extension`.
- Read the strategy tree recursively: connect parent limitations/expectations to child strategy records when the evidence supports that transfer.
- Explain information-to-decision logic instead of only listing evidence.

## Concrete Detail Requirements

Generated ideas must be specific enough for a material scientist to understand what would be made and why. Extract details from Stage 1 before writing the idea:

- route: MOCVD, PLD, LTG deposition, sequential ablation, SuperPower coated-conductor formulation, or another exact route named in evidence;
- material/form: YBCO, GdBCO, SmBCO, NdBCO, `(Gd,Y)BCO`, REBCO coated conductor, epitaxial thin film, multilayer, tape;
- additive/loading: examples include `7.5 at.% Zr`, `5 mol.% BaZrO3`, `2 vol% BZO`, `15% BZO`, `x=0`/`x=0.04`;
- defect architecture: splayed/c-axis BZO nanorods, ab-plane BZO nanodot arrays, RE2O3 precipitates, BCO dots, stacking faults, interface-strain defects;
- validation conditions: 77 K/1 T, 4.2 K/5-45 T, 30 T/4.2 K, matching field, nanorod diameter/density, angular Ic/Jc, Fp, Hirr/BIrr;
- controls: undoped, Zr-free, pure matrix, c-axis-only BZO, BZO-only nanorods, formulation series, or matrix-composition comparison.

If Stage 1 does not directly contain one of these items, the idea may still propose a labeled `inferred_design` hypothesis. The hypothesis must name the evidence basis, physical rationale, uncertainty, and validation/control that would test it. Do not replace missing detail with a broad list of possible methods.

## Tuning Strategy Field

Every idea must include a separate `tuning_strategy` field, distinct from mechanism and validation:

- `dominant_dimensions`: Stage 1 dimensions used, such as Composition tuning, Texture tuning, Interface tuning, Stress tuning, or Grain boundary tuning.
- `strategy_steps`: concrete Stage 1 `tuning_strategy` records with dimension, strategy, expected effect, source node, and record id.
- `integrated_strategy`: one concise sentence explaining how the steps are combined in this new idea.
- `controllable_variables`: concrete variables that can be adjusted, such as APC loading, nanorod density/orientation, layer architecture, deposition temperature anchor, or validation field window.

Do not write only a generic phrase such as `composition tuning + texture tuning`; include the actual controllable operations from Stage 1.

## Boundaries

- Evidence-based hypotheses are allowed for dopants, ratios, routes, process windows, optimal regions, and performance targets when they are explicitly labeled `inferred_design` or `hypothesis`.
- Do not copy external proposal-agent fields, such as template-library IDs, English-only JSON wrappers, `<final_idea>` tags, or full protocol/outcome requirements.
- Use external idea-agent examples only as prompt-writing references: borrow multi-dimension reasoning and avoid mechanical permutations, but keep the SupraMAS Stage 2 output schema.
- For every inferred ratio, route, process window, or optimal region, include the evidence basis, physical rationale, uncertainty/assumption, and validation/control. Never mark inferred details as `evidence_supported`.
- Never fabricate papers, DOI, chunk text, or quote unsupported values as literature facts.
- The validation section may list methods, variables, characterization, tests, and controls; do not write a full protocol.
- Prohibited placeholder pattern: naming several fabrication methods as alternatives without tying the chosen route to a specific evidence chunk.
