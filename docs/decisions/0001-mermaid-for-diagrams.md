# 0001. Mermaid for diagrams

- **Date:** 2026-04-27
- **Status:** Accepted

## Context

We needed workflow and component diagrams for the three system phases (Deploy / Runtime forecast / Evaluation), driven by two motivations:

1. **Engineers reading the repo** should be able to understand component interactions without launching a separate tool.
2. **The diagrams will also be used in slide presentations.**

The diagrams must render correctly on GitHub (where this repo lives), live next to the code they describe (so they don't drift), diff cleanly in PRs, and be exportable to images for slides.

We considered four candidates:

- **Mermaid** — text-based, fenced ` ```mermaid ` blocks in markdown.
- **PlantUML** — text-based, but requires either a server or local Java to render.
- **draw.io** (`.drawio` XML files) — GUI editor, XML-on-disk.
- **Excalidraw** (`.excalidraw` JSON files) — GUI editor, JSON-on-disk.

## Decision

Use **Mermaid** in fenced code blocks inside markdown files under `docs/diagrams/`.

- Workflow diagrams: `flowchart TD`/`LR` for single-actor flows, `sequenceDiagram` when temporal sequence across multiple actors matters.
- Component diagrams: `graph TB`/`LR` with `subgraph` blocks for module groupings.

## Rationale

| Criterion                              | Mermaid | PlantUML | draw.io | Excalidraw |
|----------------------------------------|:-------:|:--------:|:-------:|:----------:|
| Renders on GitHub natively             | ✅      | ❌       | ❌      | ❌         |
| Inline in markdown next to docs        | ✅      | partial  | ❌      | ❌         |
| Diffs cleanly in PRs                   | ✅      | ✅       | ❌      | ❌         |
| Exports to PNG for slides              | ✅      | ✅       | ✅      | ✅         |
| Engineer can edit without GUI          | ✅      | ✅       | ❌      | ❌         |
| No external server / runtime needed    | ✅      | ❌       | ✅      | ✅         |

Mermaid is the only candidate that satisfies all six criteria. PlantUML is the closest competitor but loses on native GitHub rendering — the property that keeps diagrams discoverable from the README and PR review surface.

## Consequences

- **Easier**
  - Diagrams stay in version control and are PR-reviewable.
  - No GUI tool required; engineers update diagrams in the same commit as the code change.
  - Anyone reading the repo on github.com sees the rendered diagrams immediately.
- **Harder**
  - Mermaid's auto-layout is less flexible than draw.io's free-form canvas. Very dense component diagrams may need to be split across multiple `subgraph` blocks (already did this for Phase 2's component view).
  - Some Mermaid syntax edge cases (parentheses inside labels, `&` characters) require workarounds.
- **Watch for**
  - If a future diagram type isn't supported by Mermaid (e.g., a UML deployment diagram with stereotypes, or a detailed ER diagram), revisit this decision rather than forcing it. PlantUML would be the most likely successor — also markdown-resident — and a Supersedes ADR can be written then.
  - Mermaid versions on GitHub vs. local renderers can drift. If a diagram renders on github.com but not in VSCode (or vice versa), that's a tooling issue, not an architectural one — pin the Mermaid version in CI if it becomes a recurring problem.
