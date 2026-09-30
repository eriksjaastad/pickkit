# Case-study journal research index

**Purpose:** Citation map for pickkit case-study chapters (PLAN §3 / precursor ROADMAP §2).  
This file is **research fuel only** — paths + short incident→guardrail themes. It does **not** reproduce journal prose, client content, prompts, or absolute machine paths.

**Private corpus:** `~/projects/ai-journal` (not part of this repo). Citations below are relative to that tree.

**How to use:** When drafting Chapters A–J, open the cited entry privately, extract the lesson, then write public prose that states the **rule** and which plugin/lib owns it. Do not paste journal text into public docs.

---

## Omit from public narrative

Do **not** copy any of the following from journals (or precursor trees) into pickkit, GitHub, or website drafts:

| Omit | Why |
|------|-----|
| Client / project codenames, batch folder names, subject/character labels | Identifying; precursor privacy track |
| Absolute paths (`/Users/...`, `/Volumes/...`, drive labels) | Machine + client fingerprint |
| Private prompts, YAML prompt bodies, caption text, training prompts | Client IP / content |
| Screenshots or thumbnails from real batches | Content leakage |
| Boss / employer / invoice / personal details from narrative journals | Out of scope for toolkit story |
| Exact DB row dumps, recovered training payloads, email fragments | Secrets / PII adjacent |
| Scrub-forward of precursor script paths as if they were pickkit APIs | Precursor is reference-only; rewrite clean |
| Ethnicity / demographic taxonomies used as grouping examples | Sensitive; public story uses opaque “metadata bins” |

**Safe to publish (after rewrite):** the *guardrail* (“companions move together”, “crop is the only image writer”, “trash not silent delete”, “decisions are data”), mapped to a pickkit plugin/lib name.

**When unsure:** leave it out of the public chapter; keep the citation here for Erik-only drafting.

---

## Plugin / lib legend

| Key | pickkit package | Case-study chapters (typical) |
|-----|-----------------|-------------------------------|
| intake | `intake_init` | C |
| review | `review_select` | D, H |
| crop | `multi_crop` | E, H, I |
| finish | `finish_package` | G |
| character | `character_tools` | F |
| dupes | `duplicate_finder` | F |
| viewer | `directory_viewer` | F |
| lib-safety | `lib_safety` | C, E, G, H (cross-cutting) |
| lib-metrics | (maybe / precursor dashboard) | I |
| narrative | (no single package) | A, B, J |

---

## Citation table

Dates are journal entry timestamps (UTC as stored). Themes are one-line **incident → guardrail** only.

| Date (UTC) | Citation (under ai-journal/) | Theme (incident → guardrail) | Maps to | Chapters |
|------------|------------------------------|------------------------------|---------|----------|
| 2025-09-18 | `entries/2025/2025-09-18T05-43-21Z__claude__file-recovery-and-workflow-organization-september-18-2025.md` | Bad move / orphaned sidecars → filename-stem pairing (never mtime); reunite image+sidecar; verify after moves | lib-safety, intake | B, C, H |
| 2025-09-21 | `entries/2025/2025-09-21T18-59-12Z__chatgpt__image-workflow-optimization-case-study.md` | Manual click workflow too slow at ~10k+ images → web select + batch crop + grouping as named tools | review, crop, character, narrative | A, B, D, E, F |
| 2025-09-21 | `entries/2025/2025-09-21T09-00-00Z__claude__workflow-reorganization-and-image-recovery.md` | Script order chaos → spine order (select → group/sort → crop → multi-dir review); recovery after mis-ordered work | intake, review, character, crop, viewer | C, D, F, H |
| 2025-09-22 | `entries/2025/2025-09-22T09-00-00Z__claude__similarity-mapping-and-image-recovery.md` | Lost/misplaced images during regroup → similarity maps + recovery pass; layout aids human triage | character, viewer, lib-safety | F, H |
| 2025-09-23 | `entries/2025/2025-09-23T23-30-00Z__claude__ergonomic-image-selector-ui-revolution.md` | Selector ergonomics debt → human-speed review UI (not a file-safety chapter; cite for D only) | review | D |
| 2025-09-24 | `entries/2025/2025-09-24T19-15-00Z__claude__productivity-dashboard-system-development__recovered-1.md` | No visibility into throughput → activity/file op metrics as first-class toolkit concern | lib-metrics, intake | I, C |
| 2025-09-26 | `entries/2025/2025-09-26T22-00-00Z__claude__massive-productivity-breakthrough-and-crop-tool-perfection.md` | Crop tool skipped ahead across directories → batch index correctness; crop is high-volume sole writer | crop | E, H, I |
| 2025-10-05 | `entries/2025/2025-10-05T20-00-00Z__claude__companion-file-bug-fix.md` | Delete/move left orphan `.caption` (and similar) → **all** same-stem companions must travel; one buggy delete path breaks the invariant | lib-safety, review, viewer | H, D, F |
| 2025-10-05 | `entries/2025/2025-10-05T21-12-16Z__chatgpt__crop-progress-tracking-system-design.md` | Crop progress invisible at scale → track crop queue / progress as data | crop, lib-metrics | E, I |
| 2025-10-05 | `entries/2025/2025-10-05T23-59-00Z__chatgpt__selector-crop-logging-and-tests.md` | Decisions not testable → log selector/crop actions; tests around routing | review, crop, lib-safety | D, E, H |
| 2025-10-06 | `entries/2025/2025-10-06T15-26-57Z__chatgpt__spec-prezip-stager.md` | Delivery ZIP must not leak junk → allowlist/ban extensions; dry-run default; close manifest on success | finish, lib-safety | G, H |
| 2025-10-06 | `entries/2025/2025-10-06T20-42-06Z__chatgpt__fast-volume-near-duplicate-thinning-workflow-automation-plan.md` | Redundant near-dups waste review → non-destructive stage-to-review; companion-aware; reports before deletes | dupes, lib-safety | F, H |
| 2025-10-06 | `entries/2025/2025-10-06T16-19-45Z__chatgpt__workflow-comparison-matrix.md` | Bare tools vs built tools contrast material → without/with matrix for narrative | narrative | A, B, J |
| 2025-10-16 | `entries/2025/2025-10-16T22-08-47Z__chatgpt__case-studies-image-processing-pipeline-automation.md` | Earlier case-study notes on pipeline automation → chapter seed (rewrite; no scrub-forward) | narrative | A, J |
| 2025-10-20 | `entries/2025/2025-10-20T03-20-53Z__chatgpt__companion-file-system-complete-guide.md` | Companions must be centralized → single move/delete API used by all tools | lib-safety | H, C |
| 2025-10-20 | `entries/2025/2025-10-20T13-56-00Z__chatgpt__file-safety-reminder-checklist.md` | Session amnesia → checklist: crop-only writer; trash; companions; audit before commit | lib-safety, crop | H, E |
| 2025-10-20 | `entries/2025/2025-10-20T00-39-32Z__chatgpt__character-processor-refactor-summary.md` | Grouping logic split across tools → processor owns bins; sorter stays interactive | character | F |
| 2025-10-20 | `entries/2025/2025-10-20T02-58-46Z__chatgpt__auto-grouping-guide-for-character-sorter.md` | Auto-group UX moved out of sorter → CLI/processor path; public prose uses opaque metadata bins only | character | F |
| 2025-10-21 | `entries/2025/2025-10-21T15-09-32Z__chatgpt__ai-assisted-reviewer-batch-processing-design.md` | Review at volume needs batch/AI assist design → decisions + routing as product surface | review | D |
| 2025-10-25 | `entries/2025/2025-10-25T16-37-28Z__claude__ai-training-decisions-v3-complete-implementation-plan.md` | AI pick/crop without user correction trail → group-linked decision DB (recommend vs final) | review, crop | D, E, H |
| 2025-10-22 | `entries/2025/2025-10-22T11-22-33Z__chatgpt__desktop-multi-crop-performance-fix.md` | Sync redraw froze crop UI → non-blocking draw; crop ergonomics affect throughput | crop | E, I |
| 2025-10-26 | `entries/2025/2025-10-26T00-53-08Z__chatgpt__ai-assisted-reviewer-file-routing-specification.md` | keep / crop / reject must land in known stage dirs → explicit routing + decision logs | review, crop, lib-safety | D, E, H |
| 2025-10-26 | `entries/2025/2025-10-26T00-53-18Z__claude__file-safety-system.md` | Silent modify of production → layered rules + audit script + operation log; only crop writes new pixels | lib-safety, crop | H, E |
| 2025-10-28 | `entries/2025/2025-10-28T07-15-00Z__gpt5__image-workflow-desktop-crop-updates-and-todo-hygiene.md` | Crop UX noise / interactive movers → quieter crop UI; non-interactive `--yes` for scripted moves | crop, lib-safety | E, H |
| 2025-10-28 | `entries/2025/2025-10-28T23-00-00Z__claudeCode__crop-progress-dashboard-fixes-zero-git-disasters.md` | Progress/dashboard honesty after bad days → metrics must match filesystem reality | crop, lib-metrics | E, I, H |
| 2025-10-30 | `entries/2025/2025-10-30T01-43-49Z__grok-code__comprehensive-safety-monitoring-system.md` | Failures silent → loud validation, backup health, op logging; safety is ops not only code | lib-safety, lib-metrics | H, I |
| 2025-10-31 | `entries/2025/2025-10-31T23-00-00Z__claudeCode__catastrophic-data-loss-to-genius-recovery-five-beers-and-product-dreams.md` | DB vs filesystem drift / near-loss → recover from files; dry-run on temp DB; never copy AI fields over human truth; product idea = guardrails | lib-safety, review, crop, intake | H, C, D, E, J |

### Supporting / secondary (cite sparingly)

| Date (UTC) | Citation | Theme | Maps to | Chapters |
|------------|----------|-------|---------|----------|
| 2025-09-21 | `entries/2025/2025-09-21T09-00-00Z__claude__workflow-reorganization-batch-crop-enhancements.md` | Batch crop enhancements alongside reorg | crop | E |
| 2025-09-25 | `entries/2025/2025-09-25T19-15-00Z__claude__revolutionary-workflow-transformation-and-yaml-breakthrough.md` | Sidecar/YAML role in workflow speed | intake, lib-safety | C, H |
| 2025-10-05 | `entries/2025/2025-10-05T21-12-23Z__chatgpt__professional-case-study-generative-media-pipeline-automation-workflow-optimizati.md` | Professional case-study draft seed (rewrite heavily; omit client specifics) | narrative | A, J |
| 2025-10-20 | `entries/2025/2025-10-20T14-53-28Z__chatgpt__automation-reviewer-technical-specification.md` | Automated reviewer spec lineage | review | D |
| 2025-10-20 | `entries/2025/2025-10-20T16-43-54Z__chatgpt__ai-phase-3-complete-rule-based-reviewer-tool.md` | Rule-based reviewer phase | review | D |
| 2025-10-21 | `entries/2025/2025-10-21T21-54-54Z__chatgpt__ai-assisted-reviewer-batch-processing-implementation.md` | Batch processing implementation notes | review | D |
| 2025-10-26 | `entries/2025/2025-10-26T01-13-57Z__chatgpt__ai-assisted-reviewer.md` | Reviewer overview snapshot | review | D |
| 2025-10-28 | `entries/2025/2025-10-28T18-00-00Z__claudeCode__linting-apocalypse-crop-tool-resurrection.md` | Tool breakage under churn → keep crop path green; hygiene ≠ product story | crop | E |

### Explicitly out of Chapter H scope (do not lean on for file/workflow guardrails)

| Citation pattern | Reason |
|------------------|--------|
| `*git-disaster*`, `*git-repository-recovery*`, `*disaster-recovery-guide*` (2025-10-25/26) | Git/repo recovery, not image-file workflow (ROADMAP §2 Chapter H note) |
| `*3d-pose*`, `*3d-mesh*`, `*ai-character-creation*` (late 2025 / 2026) | Different product line; not pickkit batch spine |
| Most 2026 Auxesis / “pipeline learned to see” venture entries | Unrelated automation pipeline; not image batch tooling |

---

## Chapter checklist (fill later)

| Chapter | Needs from this index | Status |
|---------|----------------------|--------|
| A — Assignment | Scale + done definition from 2025-09-21 case study | indexed |
| B — Day zero | Manual pain + early recovery incidents | indexed |
| C — Intake | Manifest / tracking / recovery motivation | indexed |
| D — Review | Routing, decisions-as-data, AI assist lineage | indexed |
| E — Crop | Sole writer, perf, progress, batch correctness | indexed |
| F — Middle | Character / dupes / viewer citations | indexed |
| G — Finish | Prezip allowlist + manifest close | indexed |
| H — Incidents→guardrails | Companion, safety layers, recovery,DB↔FS | indexed |
| I — Efficiency | Dashboard + session throughput entries | indexed |
| J — Public plugins | Narrative + extract discipline (no scrub-forward) | indexed |

---

## Counts

- **Primary citations:** 27  
- **Secondary citations:** 8  
- **Out-of-scope notes:** 3 patterns (not counted as chapter fuel)

Index started 2026-09-30 from PLAN phase “case-study research index” + precursor ROADMAP §2. Expand with more 2025 entries if chapter drafts find gaps; keep omit rules absolute.
