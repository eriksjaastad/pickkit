# pickkit

**A kit for picking the best images from large batches. The only image rewrite is crop.**

Not a general image-processing suite. Not Lightroom. Not the private client pipeline.

pickkit is a public, composable set of workflow steps (plugins) for:

1. **Intake / initialize** — point at a directory; tracking, sidecars, step recording
2. **Review / select** — pick keepers from a huge pile
3. **Crop** — the only step allowed to write new image pixels
4. **Finish / package** — close out and stage a delivery
5. **Shared safety** — move-don’t-modify originals, companions together, recoverable deletes

Middle tools (character sort, duplicate find, multi-dir viewer) may join after the core spine.

## Precursor

Private lessons live in `~/projects/image-workflow` (read-only reference).  
See [precursor.md](precursor.md). **Do not scrub-and-publish that tree.**

## Sibling

[clipstash](https://github.com/eriksjaastad/clipstash) is the smaller job→tool case study (video still + title + URL packets).

## Status

Scaffolded 2026-09-26: monorepo layout + synthetic sandbox fixtures; **lib-safety** (#7650), **intake-init**, **review-select**, and **multi-crop** implemented. Plan: [PLAN.md](PLAN.md). Issues: [ISSUES.md](ISSUES.md).

## License

TBD (MIT expected when the public GitHub repo opens).
