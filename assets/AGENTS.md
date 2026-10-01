# SupraMAS: Strategy Mining and Idea Design on DeepSeek Harness

This project implements Stage 1 literature-grounded strategy tree mining and Stage 2 evidence-traced superconducting materials idea design, running on DeepSeek Harness.

## Execution Model on DeepSeek Harness

The project is packaged as a DeepSeek Harness bundle at `packages/supramas-dsh/`. Nothing here depends on Codex, the Codex SDK, or `.codex/` agent files.

## Where you are running

The delegation tools below exist only when the bundle is active. **Check your own tool list before assuming they are there.**

- **Bundle active** (CLI with `--patch`, or a profile that has `supramas-dsh` installed): call the named tools directly.
- **Bundle not active** (a plain session, e.g. the desktop/Web UI without the plugin installed): delegate through the generic `subagent` tool instead, pointing it at the role contract. Do not stop and tell the user a tool is missing.

```json
{
  "prompt": "Act as strategy-builder-agent. Your full role contract is in packages/supramas-dsh/agents/strategy-builder-agent.md — read it first. Build one complete paper_node for this payload: { ..., papers_dir: runs/{job_id}/papers }. Save selected paper chunks under the provided papers_dir before returning. Return JSON only."
}
```

The same substitution applies to every delegation role: `strategy_reviewer`, `idea_expert`, `idea_review`, `idea_proximity`, `idea_ranking`, `idea_evolution`.

### Running the pipeline from a chat session

You do not have to use the named tools to run SupraMAS. In any session with `bash`:

```bash
python scripts/stage0_task_setup.py --research-goal "..." --job-id <id>      # task setup
python scripts/stage1_strategy_tree_builder.py --input-task runs/<id>/input_task.yaml
python scripts/stage2_idea_design.py --run-dir runs/<id>
```

Those scripts drive their own DeepSeek Harness run, so **prefer them for a full stage** — they also enforce the deterministic assembly gate and archive the session tree. Use delegation tools for bounded work inside a stage.

A chat session driving a stage itself should follow the same contract: keep `runs/{job_id}/tree_state.json` current, delegate node construction and review, and export only reviewer-accepted nodes and edges.

### Running a task through the bundle (CLI)

```bash
dsh --profile headless --patch packages/supramas-dsh/cordis.patch.yml "<task>"
```

The Python orchestration layer wraps that same command:

```bash
python scripts/stage0_task_setup.py --research-goal "..." --job-id ...
python scripts/stage1_strategy_tree_builder.py --input-task runs/{job_id}/input_task.yaml
python scripts/stage2_idea_design.py --run-dir runs/{job_id}
```

### Roles

Roles come in two kinds, and the difference matters:

- **Coordinator roles** run as the main-session persona: `task-setup-agent`, `strategy-mining-agent`, `idea-design-agent`. Their contracts live in `packages/supramas-dsh/agents/`.
- **Delegation roles** are registered as named subagent tools by the bundle patch when it is active. Call them by name; do not restate their contracts in the prompt.

| Delegation tool | Contract source | Write access |
| --- | --- | --- |
| `strategy_builder` | `packages/supramas-dsh/agents/strategy-builder-agent.md` | full |
| `strategy_reviewer` | `packages/supramas-dsh/agents/strategy-tree-reviewer.md` | denied (`toolFilter`) |
| `idea_expert` | `packages/supramas-dsh/agents/idea-expert-agent.md` | full |
| `idea_review` | `packages/supramas-dsh/agents/idea-review-agent.md` | denied (`toolFilter`) |
| `idea_proximity` | `packages/supramas-dsh/agents/idea-proximity-agent.md` | full |
| `idea_ranking` | `packages/supramas-dsh/agents/idea-ranking-agent.md` | full |
| `idea_evolution` | `packages/supramas-dsh/agents/idea-evolution-agent.md` | full |

`packages/supramas-dsh/agents/*.md` is the single source of truth for role contracts. `packages/supramas-dsh/cordis.patch.yml` is generated from them and must not be edited by hand:

```bash
python scripts/build_supramas_patch.py           # regenerate the patch
python scripts/build_supramas_patch.py --check   # verify it is current
```

### Skills

Skills are authored under `skills/` and linked into `.dsh/skills`, the DeepSeek Harness project skill root:

```bash
sh scripts/link_skills.sh --replace-existing
python scripts/dsh_skill_lint.py skills --fix    # DeepSeek Harness drops invalid frontmatter silently
```

Load a skill with the `skill` tool. The literature skills are `research-lit`, `arxiv`, `semantic-scholar`, `openalex`, `deepxiv`, and `exa-search`; the workflow skills are `strategy-tree-builder`, `strategy-tree-validation`, `stage2-idea-design-loop`, `stage2-idea-review`, `stage2-idea-proximity`, `stage2-idea-ranking`, `stage2-idea-evolution`, and `superconducting-materials-idea-expert`.

### Run State and Logs

- `runs/{job_id}/tree_state.json` is the authoritative resume checkpoint. Update it after every reviewer decision, retry, terminal frontier status, accepted node, and accepted edge.
- Do not rely on `--session-id` resumption to continue a run. DeepSeek Harness only adopts a session that already exists and matches the current working directory and profile preset; a fresh session plus `tree_state.json` is the supported resume path.
- Session transcripts are archived to `runs/{job_id}/logs/dsh_sessions/<session-id>/` after each stage.

## Request Routing Table

| User request | Route |
| --- | --- |
| Create or refine a Stage 1 `input_task.yaml` from a research goal | Main session acts as `task-setup-agent` and asks the user for missing choices before writing `runs/{job_id}/input_task.yaml`. Do not delegate topic-only setup unless the user explicitly approved defaults or supplied a complete payload. |
| Run Stage 1 strategy mining from `runs/{job_id}/input_task.yaml` | Main session acts as the `strategy-mining-agent` coordinator, then delegates bounded work to `strategy_builder` and `strategy_reviewer`. |
| Build one complete paper node from a topic or expectation | Call `strategy_builder` with the task payload. |
| Review a paper node, edge, or evidence record | Call `strategy_reviewer`. Never accept a node or edge without its explicit `accept` decision. |
| Run Stage 2 idea design from a Stage 1 run directory | Use `python scripts/stage2_idea_design.py --run-dir runs/{job_id}`, which starts `idea-design-agent`. Do not use a deterministic local direct-generation runner. |
| Generate candidate superconducting materials ideas | Call `idea_expert`; each idea must cite Stage 1 evidence. |
| Review a Stage 2 idea | Call `idea_review`; only accepted ideas may enter final output. |
| Cluster, deduplicate, or diversify Stage 2 ideas | Call `idea_proximity`. |
| Rank Stage 2 ideas | Call `idea_ranking`; rank only reviewed ideas. |
| Evolve Stage 2 ideas | Call `idea_evolution`; evolved ideas must return to review before ranking. |

## Delegation Contracts

Pass the complete task payload inside the tool's `prompt`. Keep project fields such as `input_task_path`, `run_dir`, `output_dir`, `research_topic`, `papers_dir`, and `reviewer_feedback` in the prompt body.

```json
{
  "prompt": "Build one complete paper_node for this payload: { ..., papers_dir: runs/{job_id}/papers }. Save selected paper chunks under the provided papers_dir before returning. Return JSON only, following your role output contract. Do not mark the node as accepted."
}
```

```json
{
  "prompt": "Review this paper node/edge payload: { ..., papers_dir: runs/{job_id}/papers }. Verify local papers_dir chunks. Return JSON only with decision=accept|revise|reject."
}
```

Start independent delegations together in one message and continue useful work while they run.

## Stage 1 Workflow

0. If no task file exists, the main session acts as `task-setup-agent` and asks the user to confirm inferred material scope, target properties, job id, and recursive depth. Width is unbounded by default (`max_branch_per_node: null`, `target_child_nodes: null`) with one root node. Delegate task setup only after the user explicitly approves defaults or supplies a complete task payload.
1. The main session reads `runs/{job_id}/input_task.yaml` and acts as the `strategy-mining-agent` coordinator.
2. For the root literature survey, call `strategy_builder`.
3. For root evidence review, call `strategy_reviewer`.
4. If the reviewer returns `revise`, call `strategy_builder` again with `reviewer_feedback` in the prompt.
5. Select only reviewer-accepted root nodes.
6. Use the `strategy-tree-builder` skill to formulate limitation-resolution tasks.
7. For each frontier limitation, repeat the builder/reviewer handoffs.
8. Assemble only reviewer-accepted nodes and edges.
9. Export only `strategy_tree.json`, `node_review_log.jsonl`, and `review_report.md`.

Do not use `strategy_reviewer` only as a final validator. It participates during every node and edge construction loop.

Build root and child nodes through `strategy_builder`. The builder must use its literature-search skills (`research-lit`, `arxiv`, `semantic-scholar`, `openalex`, `deepxiv`, `exa-search` as useful) to find candidate papers, then persist the selected paper metadata/artifacts and evidence chunks under the task-provided `papers_dir`.

## Stage 2 Workflow

Run Stage 2 from a completed or partially completed Stage 1 run:

```bash
python scripts/stage2_idea_design.py --run-dir runs/{job_id}
```

The runner starts `idea-design-agent`, which coordinates `idea_expert`, `idea_review`, `idea_proximity`, `idea_ranking`, and `idea_evolution`. It reads `runs/{job_id}/outputs/strategy_tree.json` when available and falls back to `runs/{job_id}/tree_state.json` for debug runs. It writes:

```text
runs/{job_id}/stage2/idea_state.json
runs/{job_id}/stage2/idea_pool.json
runs/{job_id}/stage2/idea_review_log.jsonl
runs/{job_id}/stage2/idea_similarity_graph.json
runs/{job_id}/stage2/idea_ranking.json
runs/{job_id}/stage2/final_idea_designs.md
```

## Schema Validation

After a Stage 1 run exports `strategy_tree.json`, validate it with:

```bash
python scripts/validate_schema.py runs/{job_id}/outputs/strategy_tree.json --schema schemas/strategy_tree.schema.json
```

Stage 2 validates `idea_state.json` against `schemas/idea_design.schema.json` automatically at the end of the run.

## Scientific Domain

Default domain: **REBCO high-temperature superconducting films/coated conductors and flux pinning**.

Use this material context:

- Materials: REBCO, YBCO, GdBCO, SmBCO, EuBCO, mixed rare-earth barium copper oxide.
- Properties: flux pinning, vortex pinning, Jc, Ic, Fp, in-field Jc, angular dependence, c-axis pinning, isotropic pinning.
- Structures: artificial pinning centers, APCs, nanorods, nanocolumns, nanoparticles, nanodots, stacking faults, dislocations, point defects, twin boundaries, grain boundaries.
- Processes: PLD, hot-wall PLD, MOCVD, CSD, MOD, sputtering, deposition temperature, oxygen pressure, annealing, oxygenation, growth rate, film thickness.
- Typical additives: BZO, BHO, BSO, BYNO, BaZrO3, BaHfO3, BaSnO3, Ba2YNbO6, Y2O3, Y211, RE2O3, ZrO2, CeO2.

## Stage Boundary

Stage 1 must not work on:

- idea generation,
- protocol generation,
- Bayesian optimization,
- real-world feedback,
- hierarchical backtracking.

Stage 1 only builds a structured, evidence-supported strategy tree from literature.

Stage 2 may generate evidence-traced superconducting materials ideas from Stage 1 outputs. Stage 2 must not generate full experimental protocols, Bayesian optimization, real-world feedback loops, or claim that inferred designs are experimentally validated.

## Input Task Scope Semantics

For Stage 1 strategy-tree construction, `research_topic`, `material_scope`, `target_property`, and `constraints.include` / `constraints.exclude` guide literature search, candidate ranking, and coverage reporting. They are not hard acceptance filters for every paper node by default.

A Stage 1 node may be accepted when it is scientifically relevant to superconducting materials / REBCO flux-pinning strategy mining, contains evidence-supported tuning and limitation records, and can support direct, transferable, or exploratory expansion. It does not need to satisfy every narrow downstream idea-design phrase such as a specific substrate, exact co-dopant pair, or every target property unless the task explicitly labels that phrase as a hard Stage 1 node requirement.

If no single paper matches all narrow task details, build the tree from the closest evidence-rich adjacent strategy papers and record missing task-specific details as coverage gaps. Do not invent or overclaim evidence to force a match.

## Data Semantics

One strategy tree node equals one paper/article.

Inside each node:

- `strategy_records[]`: only `tuning_dimension`, `tuning_strategy`, `tuning_effect`.
- `limitation_records[]`: `limitation`, `expectation`, optional `related_record_ids`.

Never put `limitation`, `expectation`, or deprecated outcome aliases into strategy_records or edge fields.

Edges connect:

```text
parent limitation_record.expectation
  -> child paper node
```

Each edge must include `edge_type`: `direct`, `transferable`, or `exploratory`.

## Tuning Dimensions

Use exactly these dominant dimensions:

1. Composition tuning
2. Grain boundary tuning
3. Interface tuning
4. Texture tuning
5. Stress tuning

## Evidence Discipline

Every evidence-supported node and record must preserve:

- node-level paper_id
- record_id or limitation_id
- evidence chunk_id
- page if available
- evidence evidence_text
- record-level confidence

Every paper used in a node must be saved under the task-provided `papers_dir`, normally `runs/{job_id}/papers/`, and every `evidence.chunk_id` must resolve to a saved local chunk there. Do not accept placeholder, abstract-only, or one-sentence nodes unless the task explicitly allows abstract-only evidence and the reviewer accepts the limitation.

Do not invent papers, DOI, figures, values, mechanisms, dopants, process parameters, or performance improvements.
