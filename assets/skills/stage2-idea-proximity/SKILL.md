---
name: stage2-idea-proximity
description: Use when clustering Stage 2 material ideas, detecting duplicates, building similarity graphs, identifying overrepresented clusters, or finding underexplored design regions.
---

# Stage 2 Idea Proximity

Build an idea similarity graph. Do not judge scientific correctness.

## Similarity Axes

- Material system.
- APC or defect type.
- Processing route.
- Additive loading or composition anchor.
- Defect architecture and orientation: nanorods, nanodots, precipitates, stacking faults, interface/strain defects.
- Validation window: temperature, magnetic field, angular range, Jc/Ic/Fp/Hirr/BIrr target.
- Control group overlap.
- Pinning mechanism.
- Target property.
- Tuning dimensions.
- Evidence-source overlap.

## Output

```json
{
  "similarity_graph": [],
  "clusters": [],
  "duplicates": [],
  "underexplored_regions": []
}
```

## Rules

- Mark high-overlap ideas as duplicates when they differ only in wording.
- Preserve one representative per cluster for final diversity.
- Send underexplored dimensions or mechanisms to `idea-evolution-agent`.
- Do not accept or reject ideas scientifically; that is `idea-review-agent`.
- Treat two ideas as near-duplicates if they use the same matrix, same APC chemistry/loading, same route, and same defect architecture even when the titles differ.
- Treat ideas as usefully diverse when they share APC chemistry but differ in concrete architecture, such as continuous c-axis BZO nanorods versus segmented BZO/BCO multilayers or hybrid c-axis/ab-plane BZO arrays.
- Report gaps in concrete terms, e.g. `no low-temperature high-field validation idea`, `no interface/strain route`, or `overrepresented BZO nanorod-only cluster`.
