# ADR-0003 — OSS engine name: Baton

Date: 2026-09-23 · Status: accepted

## Context

The engine (core loop, drivers, gates, verticals) ships Apache-2.0 under its own name, with
**eeze.app as the commercial product**. This was the last blocker before the split; the
candidates from the naming round were *Baton*, *Halyard*, *Gantry*.

## Decision

The engine is named **Baton**. Distribution name `baton-engine` (free on PyPI and npm, checked
2026-09-23), GitHub org `baton` (free), docs/demo at `baton.eeze.app` (we own the zone), CLI and
import name `baton`. Full evidence, the exclusion of *Halyard* (a live AI-tooling product on PyPI
two weeks old) and the recorded caveats live in `docs/ENGINE-NAMING.md`.

## Consequences

- The OSS split is unblocked: extract the engine package, add the Apache-2.0 `LICENSE` + `NOTICE`,
  publish, and point the docs subdomain — checklist in the naming doc.
- The product brand stays eeze.app, so no paid surface carries "Baton" yet; a formal trademark
  screen is required before any *paid* product ever does.
- Known collision surface: the PyPI project `baton` (an unrelated 2025 wrapper) and the taken
  `baton.dev/.sh/.run` domains — mitigated by the `baton-engine` distribution name and the
  `baton.eeze.app` subdomain.
