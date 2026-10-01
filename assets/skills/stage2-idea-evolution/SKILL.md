---
name: stage2-idea-evolution
description: Use when improving Stage 2 material ideas from review feedback, ranking loss patterns, proximity clusters, diversity gaps, or risk-reduction requests.
---

# Stage 2 Idea Evolution

Create new ideas from feedback. Do not overwrite parent ideas.

## Evolution Types

- `revise`: address review issues.
- `combine`: merge strengths from top ideas.
- `simplify`: reduce overcomplex designs.
- `diversify`: cover underexplored clusters.
- `risk_reduce`: lower feasibility or physics risks.
- `grounding_enhance`: strengthen evidence trace.

## Rules

- Every evolved idea must include `parent_idea_ids` and `evolution_type`.
- Evolved ideas must return to `idea-review-agent`.
- If the same evidence or physics issue repeats for two evolution rounds, stop that direction.
- Stay within Stage 2: idea and validation concept only, no full protocol.
- Evolution must add specificity, not only new adjectives. A revised idea should fill missing route/loading/control/test details from Stage 1, or convert the gap into a labeled `inferred_design` hypothesis with evidence basis, physical rationale, uncertainty, and validation/control.
- When combining ideas, preserve concrete anchors from both parents: matrix, APC chemistry/loading, architecture, route, validation conditions, and control groups.
- When diversifying, target a named gap from proximity, such as low-temperature high-field validation, interface/strain tuning, ab-plane pinning, segmented nanorods, BSO/BHO/BCO alternatives, or flux-jump risk mitigation.

## Revision Targets

Use review feedback to create precise changes:

- `generic_method`: replace a method menu with the exact source-paper route.
- `missing_loading`: retrieve or carry forward the cited loading; if absent, generate a labeled `inferred_design` loading hypothesis only when evidence supports the APC chemistry/defect architecture, and state the rationale plus validation controls.
- `weak_control`: add a named baseline such as undoped, Zr-free, pure matrix, BZO-only, c-axis-only, or formulation series.
- `thin_mechanism`: connect composition/route to defect architecture, pinning mode, and target metric.
- `overlap_duplicate`: change architecture or validation window instead of retitling the same idea.
