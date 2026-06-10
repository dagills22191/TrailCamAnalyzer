# TrailCam Sorter

Automatically identifies animals in trail camera photos and videos using Google [SpeciesNet](https://github.com/google/speciesnet), then sorts the files into species-named folders with clean date-based filenames.

## What it does

- Classifies one representative image per trigger event (burst of photos + video)
- Applies the same species label to all files in that event (variants `_1`, `_2`, associated `.mp4`)
- Matches video-only events to classified image events fired within the same minute
- Renames output files to `yyyy-mm-dd_HH-MM-SS_Species Name.ext`
- Skips blank frames; routes uncertain/low-confidence images to a `Review` folder
- Optional blur detection: scores each burst image for sharpness and copies only the sharpest frame

**Output structure:**
```
~/TrailCamAnimals/
  Odocoileus Virginianus/
    2024-06-15_08-30-12_Odocoileus Virginianus.jpg
    2024-06-15_08-30-12_Odocoileus Virginianus_2.jpg
    2024-06-15_08-30-12_Odocoileus Virginianus.mp4
  Procyon Lotor/
    2024-06-16_19-45-03_Procyon Lotor.jpg
  Review/
    2024-06-17_07-12-44_Review.jpg
  _sort_report.json
```

## Requirements

- [Miniconda](https://docs.anaconda.com/miniconda/) or Anaconda (Python 3.11)
- ~1 GB disk space for model weights (downloaded automatically on first run to `~/.cache/kagglehub/`)
- GPU optional — runs fine on CPU at ~1–3 sec/image

**Python dependencies** (installed via pip):
| Package | Purpose |
|---|---|
| `speciesnet` | Google's species classification model (pulls in PyTorch, MegaDetector, etc.) |
| `customtkinter` | Modern GUI framework |
| `opencv-python` | Sharpness scoring (blur detection) |

## Installation

### Option A: Standalone executable (Windows)

Download and unzip `TrailCamSorter.zip`, then run `TrailCamSorter.exe`. No Python or conda required. Model weights (~1 GB) are downloaded on first run.

### Option B: From source

```bash
conda create -n trailcam python=3.11 pip -y
conda activate trailcam
pip install -r requirements.txt
```

## Usage

**GUI (recommended):**
```bash
python trailcam_sorter.py
```

**Command line:**
```bash
# Dry run — shows what would happen, copies nothing
python trailcam_sorter.py "D:/TrailCam/June2024" --dry-run

# Copy files with optional geofencing
python trailcam_sorter.py "D:/TrailCam/June2024" --country USA --region VA

# Move instead of copy, custom output folder, lower confidence threshold
python trailcam_sorter.py "D:/TrailCam/June2024" --move -o "E:/Sorted" --confidence 0.3

# Copy only the sharpest frame from each burst (reduces output volume)
python trailcam_sorter.py "D:/TrailCam/June2024" --sharpest

# Flat output — all files in one folder, no species subfolders
python trailcam_sorter.py "D:/TrailCam/June2024" --no-subfolders
```

**All options:**
```
positional:
  source              Folder to scan (recursive). Omit to open the GUI.

optional:
  -o, --output        Destination root (default: ~/TrailCamAnimals)
  -c, --confidence    Minimum confidence 0–1 (default: 0.4). Below this goes to Review/
  --country           ISO 3166-1 alpha-3 code (e.g. USA) — optional geofencing (see Notes)
  --region            US state abbreviation (e.g. VA) — only applies when country=USA
  --move              Move files instead of copying
  --no-subfolders     Put all files flat in the output folder instead of species subfolders
  --sharpest          Copy only the sharpest frame per burst (blur detection). Videos always included.
  --dry-run           Preview without touching any files
  -v, --verbose       Debug output
```

## File naming convention

The sorter expects standard trail cam filenames:
```
20240615_083012.jpg      base image (classified)
20240615_083012_1.jpg    variant
20240615_083012_2.jpg    variant
20240615_083012.mp4      video
```

Files that don't match this pattern are ignored.

## Notes

- Model weights are cached in `~/.cache/kagglehub/` after the first run
- SpeciesNet covers 2000+ species trained on 65M images (MegaDetector + EfficientNet V2 ensemble)
- On Windows, run inside a `conda activate trailcam` session or use the full Python path
- **Geofencing** (`--country`/`--region`) applies a geographic range prior from wildlife databases. Use ISO 3166-1 alpha-3 codes for country (e.g. `USA`, not `US`) and 2-letter state abbreviations for region (e.g. `VA`, not `US-VA`). Region is only supported for USA. Leaving both blank is safe.
- **Sharpness / blur detection** (`--sharpest`) scores each image in a burst using Laplacian variance and keeps only the highest-scoring frame. Useful for reducing output when your camera fires 3–5 shots per trigger. Videos are always copied regardless of this setting.
