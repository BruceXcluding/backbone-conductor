# Changelog

## 0.75.0 — Initial public preview

Backbone Conductor coordinates coding agents through a Git-backed ledger of intentions, decisions, tasks, conflicts, and review evidence. The first public preview includes CLI, HTTP, and MCP interfaces; optional DeepSeek Harness advice; authenticated member and reviewer workflows; Git audit and recovery tools; and a read-only decision lineage map.

The map shows decision supersession, status, rationale, related intentions, and reversion records. It supports search, filtering, panning, zooming, and personal card layout without changing ledger state.

This is a `0.x` preview. Deterministic checks do not prove semantic correctness; model advice cannot approve work. A distinct-person pilot, prospective real-project conflict evaluation, deployment measurements, and online model characterization remain open. See the [validation guide](docs/VALIDATION.md) and [pilot procedure](docs/PILOT.md).
