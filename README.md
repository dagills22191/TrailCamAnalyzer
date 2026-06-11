# TrailCam Sorter

Automatically identifies animals in trail camera photos and videos using Google [SpeciesNet](https://github.com/google/speciesnet), then sorts the files into species-named folders with clean date-based filenames.

## What it does

- Identifies 2000+ species (plus vehicles, birds, etc.) using Google SpeciesNet — runs on CPU, no GPU required
- Classifies one representative image per trigger event, then applies the same label to every file in that burst (variants `_1`, `_2`, associated `.mp4`)
- Matches video-only events to the nearest confidently classified image event (up to 60 seconds apart)
- Renames all output files to `yyyy-mm-dd_HH-MM-SS_Species Name.ext` for easy browsing and sorting
- Skips blank frames; routes uncertain or low-confidence results to a `Review/` folder for manual inspection
- **Copy or move** — non-destructive copy by default, or move to save disk space
- **Basic / Advanced GUI modes** — simple one-click interface by default; toggle Advanced for expert controls
- **Species subfolders** — organises output into one folder per species, or dump flat into a single folder
- **Geofencing** — optionally filter predictions by country and US state to improve accuracy in your region
- **Confidence threshold** — tune how certain the model needs to be before filing a result (default 0.4)
- **Sharpest frame selection** — when your camera fires bursts, scores each frame for sharpness and keeps only the clearest one
- **EXIF timestamp fallback** — optionally use image EXIF capture date/time when filenames do not follow the expected timestamp pattern
- **Recursive or top-level scan** — walk the full source folder tree, or scan only the top-level folder
- **Event merge window** — group images shot within N seconds of each other into a single event
- **Exact duplicate detection** — skip byte-identical files based on content hash to avoid redundant copies
- **Checkpoint / resume** — save progress to a file and resume interrupted runs without reprocessing completed events
- **CSV summary report** — optionally write species/category counts to a CSV for spreadsheet analysis
- **Dry run mode** — preview exactly what would be copied/moved without touching any files
- **Verbose logging** — per-file debug output for troubleshooting
- Saves a `_sort_report.json` summary with species counts and per-event details

**Output structure:**
```
~/TrailCamAnimals/
  White-Tailed Deer/
    2022-10-08_19-15-28_White-Tailed Deer.jpg
    2022-10-08_19-15-28_White-Tailed Deer_2.jpg
    2022-10-08_19-15-28_White-Tailed Deer.mp4
  American Black Bear/
    2022-04-11_20-00-08_American Black Bear.jpg
  Bobcat/
    2022-03-25_17-23-53_Bobcat.jpg
  Coyote/
    2022-03-21_14-39-20_Coyote.jpg
  Vehicle/
    2022-03-26_15-12-03_Vehicle.jpg
  Review/
    2022-06-17_07-12-44_Review.jpg
  _sort_report.json
  _sort_dashboard.html  (optional, via render_sort_dashboard.py)
```

## Requirements

- **Windows installer users:** no Python or conda needed — the installer bundles everything
- **From source:** [Miniconda](https://docs.anaconda.com/miniconda/) or Anaconda (Python 3.11)
- ~1 GB disk space for model weights (downloaded automatically on first run to `~/.cache/kagglehub/`)
- GPU optional — runs fine on CPU at ~1–3 sec/image

**Python dependencies** (installed via pip):
| Package | Purpose |
|---|---|
| `speciesnet` | Google's species classification model (pulls in PyTorch, MegaDetector, etc.) |
| `customtkinter` | Modern GUI framework |
| `opencv-python` | Sharpness scoring (blur detection) |

## Installation

### Option A: Windows installer (recommended)

Download `TrailCamSorter-Setup.exe` from the [Releases](../../releases) page and run it. The setup wizard installs the app to Program Files, creates a Start Menu shortcut, and registers an uninstaller. No Python or conda required. Model weights (~1 GB) are downloaded on first run.

### Option B: From source

```bash
conda create -n trailcam python=3.11 pip -y
conda activate trailcam
pip install -r requirements.txt
```

## Developer quickstart

```bash
# from repo root
conda create -n trailcam python=3.11 pip -y
conda activate trailcam
pip install -r requirements.txt

# run tests
python -m pytest -q
```

### Building the Windows installer

```powershell
# from repo root
.\installer\build.ps1

# also build portable single-file executable
.\installer\build.ps1 -OneFile

# build only portable single-file executable (skip installer)
.\installer\build.ps1 -OneFileOnly
```

Notes:
- The build script now auto-detects `pyinstaller` and Inno Setup (`ISCC.exe`) where possible.
- You can override tool paths:
  - `./installer/build.ps1 -PyInstallerExe "C:/path/to/pyinstaller.exe" -InnoExe "C:/path/to/ISCC.exe"`
- Use `-SkipInstaller` to build only `dist/TrailCamSorter/`.
- Portable onefile output path: `dist/TrailCamSorter-Portable.exe`.
- Onefile startup can be slower than onedir builds because dependencies are unpacked at launch.

## Usage

**GUI (recommended):**
```bash
python trailcam_sorter.py
```

Basic mode includes core controls (scan subfolders, move/copy, dry run), plus geofencing (country/US region) and confidence threshold. Advanced mode exposes expert options like species subfolders, sharpest-frame selection, and EXIF fallback.

**Command line:**
```bash
# Dry run — shows what would happen, copies nothing
python trailcam_sorter.py "D:/TrailCam/June2024" --dry-run

# Copy files with optional geofencing
python trailcam_sorter.py "D:/TrailCam/June2024" --country USA --region VA

# Use legacy minute-based video-only matching (rollout safety switch)
python trailcam_sorter.py "D:/TrailCam/June2024" --video-match-mode minute

# Move instead of copy, custom output folder, lower confidence threshold
python trailcam_sorter.py "D:/TrailCam/June2024" --move -o "E:/Sorted" --confidence 0.3

# Use a confidence preset profile (conservative|balanced|recall)
python trailcam_sorter.py "D:/TrailCam/June2024" --confidence-profile conservative

# Select classifier backend (currently speciesnet)
python trailcam_sorter.py "D:/TrailCam/June2024" --classifier-backend speciesnet

# Copy only the sharpest frame from each burst (reduces output volume)
python trailcam_sorter.py "D:/TrailCam/June2024" --sharpest

# EXIF fallback is enabled by default (good for raw SD-card imports)
python trailcam_sorter.py "D:/TrailCam/June2024" --use-exif-timestamps

# Advanced: disable fallback only if you intentionally want strict filename-only parsing
python trailcam_sorter.py "D:/TrailCam/June2024" --no-exif-timestamps

# Also write a species/category CSV summary for spreadsheets
python trailcam_sorter.py "D:/TrailCam/June2024" --report-csv "D:/TrailCam/sort-summary.csv"

# Merge adjacent timestamp events that are within 30 seconds
python trailcam_sorter.py "D:/TrailCam/June2024" --event-window-seconds 30

# Skip exact duplicate files by content hash
python trailcam_sorter.py "D:/TrailCam/June2024" --dedupe-exact

# Resume long runs from a local checkpoint file
python trailcam_sorter.py "D:/TrailCam/June2024" --checkpoint-file "D:/TrailCam/sort-checkpoint.json" --resume-from-checkpoint

# Flat output — all files in one folder, no species subfolders
python trailcam_sorter.py "D:/TrailCam/June2024" --no-subfolders

# Scan top-level folder only, skip subfolders
python trailcam_sorter.py "D:/TrailCam/June2024" --no-recursive

# Verbose/debug output — shows per-file detail in the log
python trailcam_sorter.py "D:/TrailCam/June2024" --verbose
```

**All options:**
```
positional:
  source              Folder to scan (recursive). Omit to open the GUI.

optional:
  -o, --output        Destination root (default: ~/TrailCamAnimals)
  -c, --confidence    Minimum confidence 0–1 (default: 0.4). Below this goes to Review/
  --confidence-profile
                      Confidence preset: conservative (0.60), balanced (0.40 default), recall (0.25)
  --classifier-backend
                      Classifier backend implementation (default: speciesnet)
  --country           ISO 3166-1 alpha-3 code (e.g. USA) — optional geofencing (see Notes)
  --region            US state abbreviation (e.g. VA) — only applies when country=USA
  --move              Move files instead of copying
  --no-subfolders     Put all files flat in the output folder instead of species subfolders
  --no-recursive      Scan only the top-level source folder; ignore subfolders
  --sharpest          Copy only the sharpest frame per burst (blur detection). Videos always included.
  --video-match-mode  Video-only match strategy: nearest (default) or minute (legacy)
  --use-exif-timestamps
                      Use image EXIF date/time when filenames don't match expected timestamp format (default: on)
  --no-exif-timestamps
                      Advanced: disable fallback and require strict timestamp-style filenames only
  --report-csv        Optional path to write species/category counts CSV
  --event-window-seconds
                      Merge adjacent timestamp events within this many seconds (default: 0, disabled)
  --dedupe-exact      Skip exact duplicate files based on content hash
  --checkpoint-file   Optional checkpoint JSON path for completed event keys
  --resume-from-checkpoint
                      Skip events already listed in --checkpoint-file
  --dry-run           Preview without touching any files
  -v, --verbose       Debug output
```

## Evaluation script (A/B comparison)

Use this helper to compare video-only assignments between legacy `minute` mode and new `nearest` mode on the same dataset.

```bash
python scripts/compare_video_match_modes.py "D:/TrailCam/June2024"

# optional geofencing + CSV output for manual audit
python scripts/compare_video_match_modes.py "D:/TrailCam/June2024" --country USA --region VA --csv "D:/TrailCam/compare.csv"
```

## Benchmark script

Use this helper to measure performance and record hardware metadata (CPU/GPU), event counts, and timing breakdown.

```bash
# fast benchmark (classifies first 200 representative images)
python scripts/benchmark_sorter.py "D:/TrailCam/June2024"

# full benchmark, persist JSON report
python scripts/benchmark_sorter.py "D:/TrailCam/June2024" --full-inference --report-json "D:/TrailCam/benchmark.json"
```

The benchmark report includes:
- CPU and GPU details
- total files/events/representative images
- per-phase timing (`group_events`, `load_model`, `inference`, `sort_files`)
- total elapsed time and inference throughput

## Local dashboard script

Generate a simple local HTML dashboard from `_sort_report.json` for quick visual review.

```bash
python scripts/render_sort_dashboard.py "D:/TrailCam/June2024/_sort_report.json"

# custom output path + page title
python scripts/render_sort_dashboard.py "D:/TrailCam/June2024/_sort_report.json" --output-html "D:/TrailCam/dashboard.html" --title "June 2024 TrailCam Run"
```

## Review remediation script

If you manually audit files in `Review/`, you can bulk reclassify them with a CSV mapping.

CSV format:

```csv
filename,new_species
2024-06-15_08-30-12_Review.jpg,Odocoileus Virginianus
2024-06-15_08-30-20_Review.mp4,Ursus Americanus
```

Usage:

```bash
python scripts/apply_review_reclassifications.py "D:/TrailCam/June2024/Review" "D:/TrailCam/June2024" "D:/TrailCam/reclassify.csv"

# copy instead of move
python scripts/apply_review_reclassifications.py "D:/TrailCam/June2024/Review" "D:/TrailCam/June2024" "D:/TrailCam/reclassify.csv" --copy
```

## File naming convention

The sorter expects standard trail cam filenames:
```
20240615_083012.jpg      base image (classified)
20240615_083012_1.jpg    variant
20240615_083012_2.jpg    variant
20240615_083012.mp4      video
```

Files that don't match this pattern use EXIF/modified-time fallback by default.
Use `--no-exif-timestamps` to force strict filename-only behavior.

## Notes

- Model weights are cached in `~/.cache/kagglehub/` after the first run
- SpeciesNet covers 2000+ species trained on 65M images (MegaDetector + EfficientNet V2 ensemble)
- On Windows, run inside a `conda activate trailcam` session or use the full Python path
- **Geofencing** (`--country`/`--region`) applies a geographic range prior from wildlife databases. Use ISO 3166-1 alpha-3 codes for country (e.g. `USA`, not `US`) and 2-letter state abbreviations for region (e.g. `VA`, not `US-VA`). Region is only supported for USA. Leaving both blank is safe.
- **Sharpness / blur detection** (`--sharpest`) scores each image in a burst using Laplacian variance and keeps only the highest-scoring frame. Useful for reducing output when your camera fires 3–5 shots per trigger. Videos are always copied regardless of this setting.
- **EXIF timestamp fallback** is enabled by default and lets non-standard image filenames (for example `DSCF0001.JPG`) still be grouped and named by capture time. If EXIF is unavailable/unreadable, file modified time is used as a fallback. These derived times are also used in output filenames. Use `--no-exif-timestamps` for strict filename-only behavior.
- `--no-exif-timestamps` is an advanced troubleshooting option. Most users should leave fallback enabled, especially when importing directly from SD cards.
- **Dry run naming** simulates collision handling, so planned destination names include suffixes (`_2`, `_3`, etc.) just like real runs when files already exist.

## Report schema (quick reference)

Each non-dry run writes `_sort_report.json` to the output folder.

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
    "Odocoileus Virginianus": 611,
    "Review": 94
  },
  "event_details": []
}
```
