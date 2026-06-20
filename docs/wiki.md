# TrailCam Sorter — Wiki

> Version 1.3.0 · Single-file Python app + Windows installer

---

## Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Installation](#installation)
4. [First Run — Model Download](#first-run--model-download)
5. [GUI Usage](#gui-usage)
6. [Command-Line Usage](#command-line-usage)
7. [All Options Reference](#all-options-reference)
8. [Output Structure](#output-structure)
9. [File Naming Convention](#file-naming-convention)
10. [Key Features In Depth](#key-features-in-depth)
11. [Confidence & Routing](#confidence--routing)
12. [Helper Scripts](#helper-scripts)
13. [Report Schema](#report-schema)
14. [Developer Guide](#developer-guide)
15. [Building the Windows Installer](#building-the-windows-installer)
16. [Troubleshooting](#troubleshooting)
17. [Roadmap](#roadmap)

---

## Overview

TrailCam Sorter automatically identifies animals in trail camera photos and videos using Google's [SpeciesNet](https://github.com/google/speciesnet) AI model, then sorts the files into species-named folders with clean date-based filenames.

**What it does in one sentence:** drop in a folder of raw trail camera files → get back an organized library of `White-Tailed Deer/`, `Coyote/`, `Review/`, etc.

**Key characteristics:**
- Identifies 2,000+ species trained on 65M images (MegaDetector + EfficientNet V2 ensemble)
- Runs entirely on CPU — no GPU required
- Non-destructive by default (copy mode)
- Works on burst sequences: classifies one representative image per trigger event, then applies the same label to all files in that burst
- No cloud upload — all inference runs locally

---

## How It Works

The pipeline has four phases, each timed and reported in `_sort_report.json`:

```
1. group_events     Scan source folder → parse filenames/EXIF → group into trigger events
2. load_model       Load SpeciesNet weights (downloads ~1 GB on first run)
3. inference        Classify one representative image per event with SpeciesNet
4. sort_files       Copy/move every file in each event to its output folder
```

### Event grouping

A "trigger event" is a cluster of files sharing the same timestamp base (e.g., `20240615_083012.jpg`, `20240615_083012_1.jpg`, `20240615_083012.mp4`). The sorter treats the whole cluster as a single unit and applies one species label to all of them.

**Timestamp sources (in priority order):**
1. Filename — `YYYYMMDD_HHMMSS` pattern
2. EXIF capture date (if `--use-exif-timestamps` is on, which is the default)
3. File modified time (final fallback)

### Representative image selection

For each event, one image is chosen for classification:
- Prefers still images over video
- If `--sharpest` is enabled, scores each image using Laplacian variance (blur detection via OpenCV) and picks the sharpest
- Otherwise picks the first image in the event

### Video-only events

Some events contain only video files (no still image). These are matched to the nearest confidently classified image event within 60 seconds. If no match is found, they are routed to `Review/`.

The `--video-match-mode` flag controls matching strategy:
- `nearest` (default) — match by smallest timestamp delta, up to 60 s
- `minute` (legacy) — match by shared minute bucket

---

## Installation

### Option A — Windows Installer (recommended)

Download `TrailCamSorter-Setup.exe` from the [Releases](../../releases) page and run it. The wizard installs to Program Files, creates a Start Menu shortcut, and registers an uninstaller. No Python or conda required.

### Option B — From Source

Requires Python 3.11+ (conda recommended):

```bash
conda create -n trailcam python=3.11 pip -y
conda activate trailcam
pip install -r requirements.txt
python trailcam_sorter.py
```

Or with a plain venv:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python trailcam_sorter.py
```

**Dependencies:**

| Package | Purpose |
|---|---|
| `speciesnet` | Google's species classification model (pulls in PyTorch, MegaDetector, etc.) |
| `customtkinter` | Modern GUI framework |
| `opencv-python` | Sharpness scoring (blur detection) |

---

## First Run — Model Download

On first launch the app downloads ~1 GB of model weights automatically. No Kaggle or HuggingFace account is required.

**What gets downloaded:**
- ~220 MB — SpeciesNet classifier weights (EfficientNet V2), from HuggingFace
- ~670 MB — MegaDetector detector weights (YOLOv5), from GitHub

**Cache location:** `%USERPROFILE%\.cache\huggingface\hub\` and `%USERPROFILE%\.cache\kagglehub\`

**Progress** is shown in the Log tab every 5 seconds:
```
Downloading via HuggingFace (no account needed)
Downloading model file: 220 MB total
  Download: 46 / 220 MB (21%) — 9.08 MB/s
  Download: 116 / 220 MB (53%) — 13.90 MB/s
  ...
Downloading md_v5a.0.0.pt (670 MB)...
  Download: 150 / 670 MB (22%)
  ...
Model ready in 374.7 s
```

If the download appears stuck (no network activity in Task Manager after several minutes), kill the app, delete any partial files from the cache folders, and relaunch.

---

## GUI Usage

Launch with no arguments to open the GUI:

```bash
python trailcam_sorter.py   # from source
# or use the Start Menu shortcut after installing
```

### Basic Mode (default)

Shows the essential controls:
- **Source folder** — folder to scan
- **Output folder** — where sorted files go (default: `~/TrailCamAnimals`)
- **Scan subfolders** — recursive scan toggle
- **Copy / Move** — non-destructive copy (default) or move
- **Dry Run** — preview what would happen without touching files
- **Country / Region** — optional geofencing for improved accuracy
- **Confidence threshold** — minimum score to accept a classification (default: 0.4)

### Advanced Mode

Toggle the Advanced switch to expose:
- **Species subfolders** — on by default; off puts all files flat in the output folder
- **Sharpest frame** — keep only the clearest image from each burst
- **EXIF timestamp fallback** — enabled by default; disable for strict filename-only parsing
- **Event merge window** — group events within N seconds of each other
- **Exact dedupe** — skip byte-identical files
- **Confidence profile** — presets: Conservative (0.60), Balanced (0.40), Recall (0.25)
- **Video match mode** — Nearest (default) or Minute (legacy)
- **CSV report** — write species counts to a CSV file
- **Checkpoint** — save/resume progress for long runs

### Tabs

- **Log** — streaming output during a run; shows model load, download progress, inference progress, and any errors
- **Preview** — live representative-image preview updates as inference runs (shows the best wildlife image found so far)
- **Summary** — appears after a run completes with species counts and timing

### Cancel behavior

Clicking Cancel during inference shows an amber warning — inference on the current batch cannot be interrupted mid-way. The cancel takes effect after the current batch finishes.

---

## Command-Line Usage

```bash
# Dry run — preview only, no files touched
python trailcam_sorter.py "D:/TrailCam/June2024" --dry-run

# Copy with geofencing
python trailcam_sorter.py "D:/TrailCam/June2024" --country USA --region VA

# Move instead of copy, custom output folder, lower confidence
python trailcam_sorter.py "D:/TrailCam/June2024" --move -o "E:/Sorted" --confidence 0.3

# Confidence preset
python trailcam_sorter.py "D:/TrailCam/June2024" --confidence-profile conservative

# Sharpest frame only per burst
python trailcam_sorter.py "D:/TrailCam/June2024" --sharpest

# Flat output (no species subfolders)
python trailcam_sorter.py "D:/TrailCam/June2024" --no-subfolders

# Top-level only (no recursive scan)
python trailcam_sorter.py "D:/TrailCam/June2024" --no-recursive

# Deduplicate + checkpoint for long runs
python trailcam_sorter.py "D:/TrailCam/June2024" --dedupe-exact \
  --checkpoint-file sort.json --resume-from-checkpoint

# CSV report
python trailcam_sorter.py "D:/TrailCam/June2024" --report-csv summary.csv

# Verbose/debug output
python trailcam_sorter.py "D:/TrailCam/June2024" --verbose
```

---

## All Options Reference

| Flag | Default | Description |
|---|---|---|
| `source` (positional) | — | Folder to scan. Omit to open GUI. |
| `-o`, `--output` | `~/TrailCamAnimals` | Destination root folder |
| `-c`, `--confidence` | `0.4` | Minimum confidence 0–1; below this → `Review/` |
| `--confidence-profile` | `balanced` | Preset: `conservative` (0.60), `balanced` (0.40), `recall` (0.25) |
| `--classifier-backend` | `speciesnet` | Classifier backend (currently only speciesnet) |
| `--country` | — | ISO 3166-1 alpha-3 (e.g. `USA`) for geofencing |
| `--region` | — | US state abbreviation (e.g. `VA`); only applies when `--country USA` |
| `--move` | off | Move files instead of copying |
| `--no-subfolders` | off | Put all files flat in output folder |
| `--no-recursive` | off | Scan top-level only, skip subfolders |
| `--sharpest` | off | Keep only the sharpest image per burst (videos always included) |
| `--video-match-mode` | `nearest` | Video-only matching: `nearest` or `minute` (legacy) |
| `--use-exif-timestamps` | on | Use EXIF date/time when filename lacks a timestamp |
| `--no-exif-timestamps` | — | Disable EXIF fallback; require strict timestamp filenames |
| `--report-csv` | — | Path to write species/category counts CSV |
| `--event-window-seconds` | `0` | Merge events within N seconds of each other |
| `--dedupe-exact` | off | Skip byte-identical files by content hash |
| `--checkpoint-file` | — | JSON file for saving/loading completed event keys |
| `--resume-from-checkpoint` | off | Skip events already in checkpoint file |
| `--dry-run` | off | Preview only — no files created or moved |
| `-v`, `--verbose` | off | Per-file debug output |
| `--version` | — | Print version and exit |

---

## Output Structure

```
~/TrailCamAnimals/
  White-Tailed Deer/
    2022-10-08_19-15-28_White-Tailed Deer.jpg
    2022-10-08_19-15-28_White-Tailed Deer_2.jpg
    2022-10-08_19-15-28_White-Tailed Deer.mp4
  American Black Bear/
    2022-04-11_20-00-08_American Black Bear.jpg
  Coyote/
    2022-03-21_14-39-20_Coyote.jpg
  Vehicle/
    2022-03-26_15-12-03_Vehicle.jpg
  Review/
    2022-06-17_07-12-44_Review.jpg
  _sort_report.json
  _sort_dashboard.html   (optional, via render_sort_dashboard.py)
```

Special folders:
- **`Review/`** — low-confidence results, unmatched video-only events, and classification failures
- **`_sort_report.json`** — full run summary with species counts, timing, and per-event detail
- **`_sort_dashboard.html`** — optional visual summary generated by `scripts/render_sort_dashboard.py`

---

## File Naming Convention

**Input (what the sorter expects):**
```
20240615_083012.jpg        base image — classified
20240615_083012_1.jpg      variant in the same burst
20240615_083012_2.jpg      variant
20240615_083012.mp4        video in the same burst
```

Files that don't match this pattern fall back to EXIF timestamp, then file modified time. Use `--no-exif-timestamps` to disable fallback and require strict filenames only.

**Output:**
```
yyyy-mm-dd_HH-MM-SS_Species Name.ext
yyyy-mm-dd_HH-MM-SS_Species Name_2.ext    (collision suffix)
```

---

## Key Features In Depth

### Geofencing

`--country USA --region VA` applies a geographic range prior from wildlife databases, filtering out species implausible for your location. This improves accuracy at the cost of potentially missing genuinely rare species.

- Country: ISO 3166-1 alpha-3 (`USA`, `CAN`, `MEX`, etc.)
- Region: 2-letter US state abbreviation (`VA`, `TX`, etc.) — USA only
- Leaving both blank is safe and works everywhere

### Sharpness / Burst Deduplication

`--sharpest` scores each still image in a burst using Laplacian variance (a standard blur detection metric) and keeps only the highest-scoring frame. Useful when your camera fires 3–5 shots per trigger. Videos are always included regardless of this setting.

Requires OpenCV (`opencv-python`). If OpenCV is unavailable, sharpness scoring is silently skipped and the first image is used.

### EXIF Timestamp Fallback

Enabled by default. Allows non-standard filenames like `DSCF0001.JPG` to still be grouped and named by capture time. Priority:
1. Timestamp-style filename
2. EXIF `DateTimeOriginal`
3. File modified time

### Confidence Profiles

| Profile | Threshold | Behavior |
|---|---|---|
| `conservative` | 0.60 | More goes to `Review/`, fewer false positives |
| `balanced` | 0.40 | Default — good for most use cases |
| `recall` | 0.25 | Maximizes detections, more false positives |

### Checkpoint / Resume

For large SD card imports that may take hours:

```bash
python trailcam_sorter.py "D:/Cam" \
  --checkpoint-file "D:/cam_progress.json" \
  --resume-from-checkpoint
```

The checkpoint file records completed event keys. If the run is interrupted, re-running with the same flags skips already-processed events.

### Exact Duplicate Detection

`--dedupe-exact` computes an MD5 hash of each file's content and skips byte-identical files. Useful when importing from multiple SD cards that may overlap.

---

## Confidence & Routing

Every classified event is routed based on its prediction score:

| Condition | Destination |
|---|---|
| Score ≥ threshold + identified species | `Species Name/` subfolder |
| Score < threshold | `Review/` |
| Blank frame detected | `Review/` |
| Classification failure | `Review/` |
| Video-only, no nearby image event | `Review/` |
| Human / Vehicle detected | `Human/` or `Vehicle/` |

---

## Helper Scripts

All scripts live in `scripts/`.

### `benchmark_sorter.py` — Performance measurement

```bash
# Fast benchmark (first 200 representative images)
python scripts/benchmark_sorter.py "D:/TrailCam/June2024"

# Full benchmark with JSON report
python scripts/benchmark_sorter.py "D:/TrailCam/June2024" \
  --full-inference --report-json "D:/TrailCam/benchmark.json"
```

Output includes CPU/GPU info, event counts, per-phase timing, and inference throughput (images/sec).

### `compare_video_match_modes.py` — A/B comparison

Compare `nearest` vs `minute` video-only matching on your dataset before committing to one:

```bash
python scripts/compare_video_match_modes.py "D:/TrailCam/June2024"

# With geofencing and CSV export
python scripts/compare_video_match_modes.py "D:/TrailCam/June2024" \
  --country USA --region VA --csv "D:/TrailCam/compare.csv"
```

### `render_sort_dashboard.py` — HTML dashboard

Generate a local visual summary from a completed run's `_sort_report.json`:

```bash
python scripts/render_sort_dashboard.py "D:/TrailCam/June2024/_sort_report.json"

# Custom output path and title
python scripts/render_sort_dashboard.py "D:/TrailCam/June2024/_sort_report.json" \
  --output-html "D:/TrailCam/dashboard.html" \
  --title "June 2024 TrailCam Run"
```

### `apply_review_reclassifications.py` — Bulk re-label

After manually auditing `Review/`, bulk reclassify files using a CSV mapping:

**CSV format:**
```csv
filename,new_species
2024-06-15_08-30-12_Review.jpg,White-Tailed Deer
2024-06-15_08-30-20_Review.mp4,American Black Bear
```

```bash
python scripts/apply_review_reclassifications.py \
  "D:/TrailCam/June2024/Review" \
  "D:/TrailCam/June2024" \
  "D:/TrailCam/reclassify.csv"

# Copy instead of move
python scripts/apply_review_reclassifications.py ... --copy
```

---

## Report Schema

Every non-dry run writes `_sort_report.json` to the output folder:

```json
{
  "generated": "2026-06-10T12:34:56.789012",
  "total_events": 1964,
  "total_files_sorted": 1803,
  "summary": {
    "classified_image_events": 1357,
    "video_only_events": 607,
    "exif_derived_events": 112,
    "mtime_derived_events": 24,
    "exact_duplicates_skipped": 31
  },
  "timings_seconds": {
    "group_events": 2.43,
    "load_model": 8.11,
    "inference": 1282.20,
    "sort_files": 14.88,
    "total_pipeline": 1308.01
  },
  "video_matching": {
    "video_only_events": 607,
    "video_matched_nearest": 521,
    "video_matched_minute": 0,
    "video_unmatched": 86
  },
  "event_key_sources": {
    "filename_events": 1828,
    "exif_derived_events": 112,
    "mtime_derived_events": 24
  },
  "duplicate_handling": {
    "exact_duplicates_skipped": 31
  },
  "species_counts": {
    "White-Tailed Deer": 611,
    "Review": 94
  },
  "event_details": []
}
```

---

## Developer Guide

### Running tests

```bash
conda activate trailcam
python -m pytest -q
```

Tests live in `tests/` and cover:

| File | What it tests |
|---|---|
| `test_sharpness.py` | Blur detection, OpenCV fallback |
| `test_grouping.py` | Event grouping logic |
| `test_path_validation.py` | Output path safety checks |
| `test_inference_batching.py` | Batch size and inference flow |
| `test_preview_selection.py` | Representative image selection |
| `test_run_summary.py` | Summary card content |
| `test_review_reclassifications.py` | Bulk reclassification script |
| `test_dashboard.py` | Dashboard render |
| `test_display_path.py` | Path display formatting |
| `test_startup_settings.py` | Settings persistence |
| `test_theme.py` | Theme/appearance mode |

### Code structure

Everything lives in a single file (`trailcam_sorter.py`) by design for easy distribution. Key sections:

| Section | Description |
|---|---|
| Constants / theme | Colors, version, UI palette |
| `group_events()` | Scan + parse + cluster files into events |
| `load_model()` | Download and initialize SpeciesNet |
| `run_classifier_backend()` | Inference loop with progress callback |
| `sort_files()` | Copy/move files to output with collision handling |
| `run_sort()` | Orchestrates all four pipeline phases |
| `TrailCamApp` | CustomTkinter GUI class |
| `main()` | CLI entry point |

---

## Building the Windows Installer

Requires:
- A virtual environment or conda env with `pip install -r requirements.txt pyinstaller`
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (installable via `winget install JRSoftware.InnoSetup`)

```powershell
# Standard build (onedir + installer)
.\installer\build.ps1

# Override tool paths if auto-detection fails
.\installer\build.ps1 `
  -PyInstallerExe ".\.venv\Scripts\pyinstaller.exe" `
  -PythonExe ".\.venv\Scripts\python.exe"

# Also build portable single-file exe
.\installer\build.ps1 -OneFile

# Skip Inno Setup step (just produce dist\TrailCamSorter\)
.\installer\build.ps1 -SkipInstaller
```

**Outputs:**
- `installer/output/TrailCamSorter-Setup.exe` — full installer (~216 MB)
- `dist/TrailCamSorter-Portable.exe` — portable single-file exe (if `-OneFile`)

The first build on a new machine takes 15–30 minutes (PyInstaller cold-analyses all of PyTorch). Subsequent builds reuse the cache and are faster.

Installing the new build over an existing installation does **not** require uninstalling first — Inno Setup detects the same `AppId` and upgrades in place.

---

## Troubleshooting

### Model download hangs on first run

1. Open Task Manager → Performance → Wi-Fi. If there is network activity, the download is in progress — it can take 5–15 minutes on a 100 Mbps connection.
2. If network is at zero, kill the app, delete any partial files from `%USERPROFILE%\.cache\huggingface\hub\` and `%USERPROFILE%\.cache\kagglehub\`, and relaunch.
3. Check the Log tab for progress lines. If you see "Downloading model file: 220 MB total" with no subsequent updates, the progress hook may not have taken effect — verify you have the latest installer build.

### App hangs at "Loading model..." with no network activity

This is usually a GPU probe hang. The app sets `CUDA_VISIBLE_DEVICES=-1` to force CPU mode and avoid this, but some systems still trigger it. Workaround: set the environment variable manually before launching:
```powershell
$env:CUDA_VISIBLE_DEVICES = "-1"
python trailcam_sorter.py
```

### Sharpness scoring not working

`--sharpest` requires OpenCV (`opencv-python`). If it's missing, all images get a sharpness score of 0 and the first image is used instead. Install it:
```bash
pip install opencv-python
```

### Geofencing not improving accuracy

- Use ISO 3166-1 alpha-3 for country (`USA`, not `US`)
- Region is 2-letter state (`VA`, not `US-VA`), and only applies when `--country USA`
- Leaving both blank is always safe

### Some species show Latin names instead of common names

This is a quirk of the SpeciesNet label set — not every species has a common name populated in the model's taxonomy. Species without a common name display their scientific name. A future enhancement may add a lookup table to normalize these.

### Files not grouped correctly

If files from the same burst end up in different events, check that filenames follow the `YYYYMMDD_HHMMSS` pattern. If they use non-standard names, ensure EXIF fallback is enabled (it is by default). Use `--verbose` to see which timestamp source was used for each event.

---

## Roadmap

See [`PLAN_phased_improvements.md`](../PLAN_phased_improvements.md) for the full tracked roadmap. Summary:

| Phase | Status | Focus |
|---|---|---|
| 1 — Safety & correctness | ✅ Complete | Path validation, clean shutdown, sharpness fallback, version flag, cancel UX |
| 2 — Run UX | 🔲 Planned | Clearer progress messaging, end-of-run summary, better error surfacing |
| 3 — Options & persistence | 🔲 Planned | Persist last-used settings, checkpoint/resume polish, CSV improvements |
| 4 — Polish | 🔲 Planned | README updates, GUI wording nits, Latin→common name label mapping |

**Deferred (future):**
- Module split (`trailcam_sorter.py` → `core/` + `ui/`) — deferred until contributors arrive
- In-app Review workflow UI
- Plugin classifier backend interface
- Local dashboard with species trends and confidence distributions
