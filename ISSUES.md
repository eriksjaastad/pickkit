# pickkit — non-blocking issues log

Running list of problems deferred while shipping. Review with Erik at end of a run.

| # | When | Area | Issue | Severity | Status |
|---|------|------|-------|----------|--------|
| 1 | 2026-09-30 | setup / agents | Some **agent/host shells** block `pip install`. Interactive Mac terminal `pip install -e ".[dev]"` works (verified 2026-09-30). Strangers: use a normal terminal or a prebuilt `.venv`. | Low | **Closed** 2026-09-30 — wontfix for product; agent-env only (documented in [docs/setup.md](docs/setup.md)) |
| 2 | 2026-09-30 | docs / E2E | README did not yet document space-safe subset extract from large ZIPs or unattended spine recipe (decisions JSONL → crop specs → finish --commit). | Low | **Closed** 2026-09-30 — see [docs/setup.md](docs/setup.md) + README Quickstart |
| 3 | 2026-09-30 | review-select | Backlog: optional helper to group by shared timestamp / stage-family (companions today are filename-stem only). Non-blocking; agents can script grouping. | Low | Open (backlog; not blocking v1) |
