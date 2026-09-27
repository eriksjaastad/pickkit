# pickkit — product & extract plan

**Status:** accepted 2026-09-26 (Erik) — spine GUIs done; middle tools 3/4/5 authorized for public v1 (2026-09-27); middle-tool library+CLI set shipped (character / dupes / viewer inventory), UIs follow-on  
**Board:** http://localhost:8000/kanban/pickkit  
**Public repo (when Erik says go):** `eriksjaastad/pickkit`  
**Precursor (private, reference-only):** `~/projects/image-workflow`  
**Owner seat:** pickkit agent (formerly ImageWorkflow)  
**Sibling:** clipstash (smaller case study)

> One-liner: A kit for picking the best images from large batches. The only image rewrite is crop.

---

## 1. Two layers

1. **Case study (large)** — ~50k-image job → best of each group; bare tooling vs tools built; journal incidents → guardrails.
2. **Plugin toolkit (public)** — sanitized composable steps inside **one** project. Artifacts of that story.

Do **not** scrub-forward the precursor. Rewrite clean. Demos use synthetic/sandbox images only.

Full chapter outline still lives in precursor `image-workflow/ROADMAP.md` (draft); evolve the public narrative here as chapters get written.

---

## 2. Plugin spine

| # | Plugin | Job | Public v1? |
|---|--------|-----|------------|
| 0 | **intake-init** | Point at a directory; manifest; sidecars/tracking; start step recording; safety baseline | **Yes** |
| 1 | **review-select** | Triage into keep / crop / reject; log decisions | **Yes** |
| 2 | **multi-crop** | Create NEW crops only; never overwrite originals | **Yes** |
| 3 | **character-tools** | Group / sort / check (may split later) | **Yes** (public v1) |
| 4 | **directory-viewer** | Multi-directory inspection | **Yes** (public v1) |
| 5 | **duplicate-finder** | Near-dup thinning | **Yes** (public v1) |
| 6 | **finish-package** | Close manifest; stage delivery ZIP | **Yes** |
| L | **lib-safety** | Shared: move-not-modify, companions, trash, audit | **Yes** |
| M | **lib-metrics** | Efficiency / snapshots hooks | **Maybe** |

**Human ingest:** copying a batch off an external drive is outside the kit; **intake-init** is still a first-class plugin after the folder exists.

---

## 3. Definition of done (kickoff)

### Toolkit v1
- Contracts documented for plugins 0, 1, 2, 6, L
- Those packages exist clean (README, tests, no client leakage)
- One end-to-end demo on **sandbox** images
- `ISSUES.md` habit for non-blocking problems

### Case study
- Chapters drafted with real journal citations (see precursor ROADMAP §2)
- Without-tools vs with-tools contrast
- Guardrails mapped to plugins/libs

### Not done criteria
- Bulk copy from image-workflow
- Publishing old GitHub history
- One repo per plugin on day one (packages-in-one-project first)
- Finishing #6900 before the spine exists

---

## 4. Delivery phases

1. Lock PLAN (this doc) + board cards for phase 1
2. Case-study research index (journal paths) — can parallel
3. Contract sketch for 0, 1, 2, 6, L on sandbox layout
4. Extract **one** template plugin end-to-end (`lib-safety` or `intake-init`)
5. Core spine: review-select + multi-crop + finish-package
6. Middle tools authorized 2026-09-27 (Erik): character-tools / directory-viewer / duplicate-finder for public v1 + case study
7. Public GitHub when Erik says go; #6650 privacy delete stays separate
8. Write case-study chapters for real

---

## 5. Coding seat rules (Erik)

- Worker = local DeepSeek via `~/bin/deepseek-pty` (never bare `deepseek -x`; no TTY hang)
- Never Cursor cloud agents for implementation
- Local exact-HEAD code review; merge when green
- Non-blocking problems → `ISSUES.md`; keep moving
- Always pass explicit `working_directory` on Mac local Shell

---

## 6. First cards to open (suggested)

1. Plan card: accept this PLAN / adjust middle-tools TBD
2. Scaffold: package layout + sandbox fixture images
3. Template plugin: `lib-safety` or `intake-init`
4. Case-study research: index 2025 ai-journal entries for incidents→guardrails

---

## 7. Revision log

| When | What |
|------|------|
| 2026-09-26 | Scaffold from clipstash↔Erik alignment; name locked **pickkit**; precursor = image-workflow. |
| 2026-09-26 | Erik accepted PLAN; first template plugin = **lib-safety**; middle tools remain TBD. |
| 2026-09-27 | MIT license added. Middle tools 3/4/5 → **Yes** (public v1) for case-study completeness; library+CLI first, UI follow-on. Spine GUIs (review/crop/finish) done. |
| 2026-09-27 | Middle-tool library+CLI set landed (character / dupes / viewer inventory); UIs follow-on. |
