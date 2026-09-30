# Setup and spine recipes

Stranger-install notes verified against a fresh local clone (venv + `pip install -e ".[dev]"`). Package READMEs remain the behaviour source of truth; this page is the path through them.

## Requirements

- Python **3.11+** (3.14 works in local verify)
- macOS / Linux assumed for path examples; quote paths with spaces
- Network access for first `pip install` (Flask, Pillow, send2trash, pytest)

## Install

```bash
git clone https://github.com/eriksjaastad/pickkit.git pickkit
cd pickkit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
pickkit-intake --help    # smoke: console script resolves
pytest -q                # expect a few hundred passing tests
```

### Host / agent pip blocks

Some automated shells block `pip install`. Symptoms: install never runs; only a pre-existing `.venv` works. Mitigations:

1. Run the install steps in a normal interactive terminal.
2. Copy or recreate `.venv` on a machine that allows pip, then activate it.
3. See [ISSUES.md](../ISSUES.md) #1 (closed: agent-env only; interactive install is fine).

Editable install from the repo root (`pip install -e ".[dev]"`) is the supported path; there is no separate conda recipe.

## Directory after install

- `.venv/` — local (gitignored)
- `sandbox/batch_a/` — tiny synthetic images + sidecars (safe to copy)
- `.scratch/` — local agent/demo scratch (gitignored); put demo batches here

## Human spine (Flask UIs)

Defaults (all localhost):

| Step | Command | URL |
|------|---------|-----|
| Intake | `pickkit-intake <batch>` | (CLI only) |
| Review | `pickkit-review <batch> --ui` | http://127.0.0.1:8765 |
| Crop | `pickkit-crop <batch> --ui` | http://127.0.0.1:8766 |
| Finish | `pickkit-finish <batch> --ui` | http://127.0.0.1:8767 |

```bash
mkdir -p .scratch/demo-batch
cp -R sandbox/batch_a/. .scratch/demo-batch/
pickkit-intake .scratch/demo-batch
pickkit-review .scratch/demo-batch --ui
# after queuing crops:
pickkit-crop .scratch/demo-batch --ui
pickkit-finish .scratch/demo-batch --ui
```

Review shortcuts: **K/C/R** or **1/2/3**. Crop: drag rectangle, **Enter** apply, **S** skip, **R** reset. Finish: read the eligible/excluded preview, then **Commit ZIP**.

Override bind with `--host` / `--port` (only valid with `--ui`).

## Space-safe paths

Always quote batch roots that contain spaces:

```bash
BATCH="/path/with spaces/my batch"
pickkit-intake "$BATCH"
pickkit-review "$BATCH" --ui
```

### Space-safe subset extract from a large ZIP

When a delivery ZIP (or client archive) is huge and you only need a stem family for a demo:

```bash
mkdir -p ".scratch/subset batch"
# Example: extract matching stage-tag stems only (adjust patterns to your names)
unzip -l "/path/to/delivery.zip" | head   # inspect names first
unzip "/path/to/delivery.zip" \
  "path/inside/zip/*stage1*" \
  -d ".scratch/subset batch"
# Flatten if the ZIP nested a folder — leave images + same-stem sidecars together
pickkit-intake ".scratch/subset batch"
```

Keep image + companion sidecars side by side before intake. pickkit pairs companions by **filename stem**, not mtime (so `foo_stage1.png` and `foo_stage1.5.png` are different stems).

## Unattended spine (JSONL / flags)

### Review decisions JSONL

One JSON object per line. Minimum fields used by the library (see `review_select` docs): `source` (path relative to batch root or basename for root-level pending files) and `action` (`keep` | `crop` | `reject`).

```bash
cat > /tmp/decisions.jsonl << 'EOF'
{"source":"img_001.png","action":"keep"}
{"source":"img_002.png","action":"crop"}
{"source":"img_003.png","action":"reject"}
EOF
pickkit-review .scratch/demo-batch --decisions /tmp/decisions.jsonl
```

### Crop specs JSONL

```bash
cat > /tmp/crops.jsonl << 'EOF'
{"source":"__crop/img_002.png","box":[0,0,32,48]}
EOF
pickkit-crop .scratch/demo-batch --crops /tmp/crops.jsonl
```

Boxes are Pillow-style `(left, top, right, bottom)` with exclusive `right`/`bottom`.

### Finish

```bash
pickkit-finish .scratch/demo-batch           # dry-run
pickkit-finish .scratch/demo-batch --commit  # delivery.zip + close manifest
pickkit-finish .scratch/demo-batch --commit --force  # overwrite existing ZIP only
```

## Middle CLIs (brief)

```bash
pickkit-character list SOURCE
pickkit-dupes exact DIR
pickkit-viewer inventory ROOT
```

Dry-run is the default for mutating character/dupes commands; pass `--commit` to apply. See package READMEs.

## Verify install quickly

```bash
pickkit-intake --help && pickkit-review --help && pickkit-crop --help && pickkit-finish --help
pytest -q
```

## Related

- [docs/safeguards.md](safeguards.md)
- [README.md](../README.md)
- [ISSUES.md](../ISSUES.md)
