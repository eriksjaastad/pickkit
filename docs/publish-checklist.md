# Publish checklist (public pickkit)

## Before any public mirror

- [x] **MIT** license present at repo root (`LICENSE`).
- [x] **Erik go-ahead** for GitHub create/push (2026-09-30).
- [x] **No client leakage** — no performer/client images, IDs, private paths, or precursor scrapes in the public tree. Demos use `sandbox/` only. `.scratch/` (incl. E2E extracts) is gitignored.
- [x] **No precursor scrub-forward** — do not publish `image-workflow` history or a cleaned copy of that tree; pickkit is a clean rewrite.
- [x] **Sandbox-only demos** in README / docs.
- [ ] **Case study home** — Synth Insight Labs website display is **later** (not this publish). Toolkit repo ships without waiting on case-study chapters.
- [x] Scrub review of `.scratch/` (ignored), journal citations (index only), and package docstrings for private names.
- [x] `ISSUES.md` reviewed: #1 closed as agent-env wontfix; #3 open backlog one-liner; no “product broken” framing.
- [x] Seat docs: `PLAN.md` aligned with MODEL_SEATS (Claude Worker / Codex Judge; no DeepSeek coding Worker).

## Local-only was OK until go-ahead

Working locally with commits on `main` and no remotes was fine until Erik authorized public `eriksjaastad/pickkit` on 2026-09-30.
