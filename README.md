# pickkit

**A kit for picking the best images from large batches. The only image rewrite is crop.**

Not a general image-processing suite. Not Lightroom. Not the private client pipeline.

pickkit is a public, composable set of workflow steps (plugins) for:

1. **Intake / initialize** — point at a directory; tracking, sidecars, step recording
2. **Review / select** — pick keepers from a huge pile
3. **Crop** — the only step allowed to write new image pixels
4. **Finish / package** — close out and stage a delivery (local finish wizard)
5. **Shared safety** — move-don’t-modify originals, companions together, recoverable deletes

Middle tools (character sort, duplicate find, multi-dir viewer) ship as library + CLI for public v1 (optional vs the four-step spine; wanted for case-study completeness); UI for the multi-dir viewer is follow-on.

## Precursor

Private lessons live in `~/projects/image-workflow` (read-only reference).  
See [precursor.md](precursor.md). **Do not scrub-and-publish that tree.**

## Sibling

[clipstash](https://github.com/eriksjaastad/clipstash) is the smaller job→tool case study (video still + title + URL packets).

## Status

Scaffolded 2026-09-26: monorepo layout + synthetic sandbox fixtures; **lib-safety** (#7650), **intake-init**, **review-select** (library + CLI + local Flask review UI), **multi-crop** (library + CLI + local Flask crop UI), and **finish-package** (library + CLI + local Flask finish wizard) implemented. Core spine GUIs done. **Middle tools** (character-tools, directory-viewer, duplicate-finder) authorized for public v1 — **character-tools**, **duplicate-finder**, and **directory-viewer** library + CLI all shipped; the Flask/Tk grid UI for directory-viewer is still follow-on. Plan: [PLAN.md](PLAN.md). Issues: [ISSUES.md](ISSUES.md). Licensed **MIT** ([LICENSE](LICENSE)).

## Case study research

Journal citation index (paths + incident→guardrail themes only; no secrets):
[docs/case-study-journal-index.md](docs/case-study-journal-index.md).
Feeds future case-study chapters; do not paste private journal prose into this tree.

## License

[MIT](LICENSE) — Copyright (c) 2026 Erik Sjaastad.
