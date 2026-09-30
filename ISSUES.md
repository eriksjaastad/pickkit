# pickkit — non-blocking issues log

Running list of problems deferred while shipping. Review with Erik at end of a run.

| # | When | Area | Issue | Severity | Status |
|---|------|------|-------|----------|--------|
| 1 | 2026-09-30 | setup / agents | Host shell blocks `pip install` (editable/dev install). Fresh checkout needs human override or prebuilt `.venv` before unattended E2E. | Low | Open |
| 2 | 2026-09-30 | docs / E2E | README does not yet document space-safe subset extract from large client ZIPs (stage-tag stems) or unattended spine recipe (decisions JSONL → crop specs → finish --commit). | Low | Open |
| 3 | 2026-09-30 | review-select | No first-class “group by shared timestamp / stage family” helper; agents must script grouping. Companions are filename-stem only (stage1 vs stage1.5 are separate). | Low | Open |
