# pickkit

**A kit for picking the best images from large batches. The only image rewrite is crop.**

Not a general image-processing suite. Not Lightroom. Not the private client pipeline.

When you are staring at tens of thousands of candidates, the expensive part is not “filters” — it is **keeping the keepers, discarding safely, and never wondering what you just lost**. pickkit is a small, composable toolkit for that job: intake a folder, triage keep / crop / reject, write **new** crop files only when needed, then stage a copy-only delivery ZIP. Shared safety primitives (companions travel together, trash instead of silent delete, dry-run before commit) are the point, not an afterthought. See [docs/safeguards.md](docs/safeguards.md).

## Quickstart

Requires **Python 3.11+**. Commands below use a local virtualenv so they do not touch the system Python.

### 1. Clone and install

```bash
git clone https://github.com/eriksjaastad/pickkit.git pickkit
cd pickkit
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -e ".[dev]"
```

If `pip install` is blocked in your environment (some agent/host shells refuse network installs), create the venv on a machine that can install, or reuse a prebuilt `.venv`, then activate it. The install that works for a normal stranger checkout is `pip install -e ".[dev]"` from the repo root.

Console scripts after install: `pickkit-intake`, `pickkit-review`, `pickkit-crop`, `pickkit-finish`, plus optional middle tools `pickkit-character`, `pickkit-dupes`, `pickkit-viewer`.

### 2. Spine on the sandbox (human UIs)

Use a **copy** of the sandbox batch so the committed fixtures stay clean. Quote paths that contain spaces.

```bash
mkdir -p .scratch/demo-batch
cp -R sandbox/batch_a/. .scratch/demo-batch/

pickkit-intake .scratch/demo-batch

pickkit-review .scratch/demo-batch --ui    # http://127.0.0.1:8765  Keep/Crop/Reject (K/C/R)
pickkit-crop   .scratch/demo-batch --ui    # http://127.0.0.1:8766  drag box, Enter=Apply
pickkit-finish .scratch/demo-batch --ui    # http://127.0.0.1:8767  preview then Commit ZIP
```

All three UIs bind **localhost only** and can run at once on those default ports (`--host` / `--port` override). Finish opens on a **dry-run preview**; nothing is written until you press **Commit ZIP** (or pass `--commit` on the CLI).

Space-safe example:

```bash
pickkit-intake "/path/with spaces/my batch"
pickkit-review "/path/with spaces/my batch" --ui
```

### 3. Same spine from the CLI (unattended / scripts)

```bash
pickkit-intake .scratch/demo-batch

# decisions JSONL: one object per line with source + action (keep|crop|reject)
pickkit-review .scratch/demo-batch --decisions decisions.jsonl
# or flag form:
# pickkit-review .scratch/demo-batch --keep img_001.png --crop img_002.png --reject img_003.png

# crops JSONL: source + box [left, top, right, bottom] (Pillow exclusive right/bottom)
pickkit-crop .scratch/demo-batch --crops crops.jsonl
# or: pickkit-crop .scratch/demo-batch --source __crop/img_002.png --box 0,0,32,48

pickkit-finish .scratch/demo-batch              # dry-run report only
pickkit-finish .scratch/demo-batch --commit     # write delivery.zip + close manifest
```

More detail (space-safe ZIP extracts, decision/crop JSONL shapes, ports): [docs/setup.md](docs/setup.md).

### 4. Tests

```bash
pytest          # or: .venv/bin/pytest
```

## Safeguards (built-in)

Visible and invisible protections are documented in **[docs/safeguards.md](docs/safeguards.md)** — sidecar/manifest tracking, move-don’t-modify originals, companions move together, recoverable deletes, backup-then-overwrite on re-intake, crop writes **new** files only, finish dry-run vs commit, and copy-only delivery ZIP.

## Middle tools (optional)

Not part of the four-step spine; useful for case-study completeness. Library + CLI shipped; interactive UIs are follow-on where noted.

| Command | Role |
|---------|------|
| `pickkit-character` | Assign images to user-named bins; companions travel; dry-run default |
| `pickkit-dupes` | Exact / near duplicates; thin extras via OS trash; dry-run default |
| `pickkit-viewer` | Read-only multi-directory inventory / compare |

See each package README under [`packages/`](packages/).

## Package map

| Package | Role |
|---------|------|
| [`lib_safety`](packages/lib_safety/) | Shared move / companions / trash / no-overwrite / audit |
| [`intake_init`](packages/intake_init/) | Point at a directory; `.pickkit/` manifest + inventory + audit |
| [`review_select`](packages/review_select/) | Keep / crop / reject triage + Flask UI `:8765` |
| [`multi_crop`](packages/multi_crop/) | NEW crops under `__cropped/` + Flask UI `:8766` |
| [`finish_package`](packages/finish_package/) | Copy-only `delivery.zip` + Flask wizard `:8767` |
| [`character_tools`](packages/character_tools/) / [`duplicate_finder`](packages/duplicate_finder/) / [`directory_viewer`](packages/directory_viewer/) | Optional middle CLIs |

## Precursor

Private lessons live in `~/projects/image-workflow` (read-only reference).  
See [precursor.md](precursor.md). **Do not scrub-and-publish that tree.**

## Sibling

[clipstash](https://github.com/eriksjaastad/clipstash) is the smaller job→tool case study (video still + title + URL packets).

## Status

Public toolkit on GitHub: [eriksjaastad/pickkit](https://github.com/eriksjaastad/pickkit) (MIT). Spine GUIs (review / crop / finish) and middle-tool library+CLI set shipped; directory-viewer grid UI is follow-on. Case-study website chapters are a later follow-up. Plan: [PLAN.md](PLAN.md). Setup: [docs/setup.md](docs/setup.md). Safeguards: [docs/safeguards.md](docs/safeguards.md). Publish checklist: [docs/publish-checklist.md](docs/publish-checklist.md). Issues: [ISSUES.md](ISSUES.md).

## Case study research

Journal citation index (paths + incident→guardrail themes only; no secrets):
[docs/case-study-journal-index.md](docs/case-study-journal-index.md).
Feeds future case-study chapters; do not paste private journal prose into this tree.

## License

[MIT](LICENSE) — Copyright (c) 2026 Erik Sjaastad.
