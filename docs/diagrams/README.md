# Diagrams

Architecture diagrams for `precog-baseline-miner`. All diagrams are written in Mermaid (see [ADR 0001](../decisions/0001-mermaid-for-diagrams.md)) and render natively on GitHub, in VSCode with the Mermaid extension, and at <https://mermaid.live>.

## Index

| #  | Diagram                                                | Read this when…                                                              |
|----|--------------------------------------------------------|------------------------------------------------------------------------------|
| 00 | [Overview](./00-overview.md)                           | you want the whole-system picture in one page                                |
| 01 | [Phase 1 — Deploy](./01-deploy.md)                     | you're setting up a new miner host or debugging `deploy.sh` / `run_miner.sh` |
| 02 | [Phase 2 — Runtime forecast](./02-runtime-forecast.md) | you're touching `forward()`, data fetchers, features, or forecast logic      |
| 03 | [Phase 3 — Evaluation / back-fill](./03-evaluation.md) | you're touching `fill_realized()`, `metrics.py`, or the forecasts.jsonl schema |

## Diagram conventions

- **Workflow diagrams** show *what happens in what order*. We use `sequenceDiagram` when temporal sequence across multiple actors matters, and `flowchart TD`/`LR` for single-actor processes with branches.
- **Component diagrams** show *what talks to what*. We use `graph TB`/`LR` with `subgraph` blocks for module groupings.
- **Arrows:** solid = synchronous call or required data flow. Dashed = optional / fallback / "not yet built."
- **Subgraph borders:** solid = exists today. Dashed = planned but not implemented (referenced as gaps in the project memory).

## When to update these

Update the affected phase diagram in the same commit as any code change that:

- Adds or removes a module under `src/precog_baseline_miner/`
- Changes the order of operations inside `forward()` or `fill_realized()`
- Adds/removes an external API (a new sentiment or futures source)
- Changes how artifacts are persisted (new JSONL file, schema bump)
