# TrailCam Sorter

Automatically identifies animals in trail camera photos and videos using Google [SpeciesNet](https://github.com/google/speciesnet), then sorts the files into species-named folders with clean date-based filenames.

## What it does

- Identifies 2000+ species (plus vehicles, birds, etc.) using Google SpeciesNet — runs on CPU, no GPU required
- Works with files straight off an SD card — reads timestamps from EXIF data when filenames don't follow a trail-cam pattern
- Classifies one representative image per trigger event, then applies the same label to every file in that burst (variants `_1`, `_2`, associated `.mp4`)
- Matches video-only events to classified image events fired within the same minute
- Renames all output files to `yyyy-mm-dd_HH-MM-SS_Species Name.ext` for easy browsing and sorting
- Skips blank frames; routes uncertain or low-confidence results to a `Review/` folder for manual inspection
- **Copy or move** — non-destructive copy by default, or move to save disk space
- **Species subfolders** — organises output into one folder per species, or dump flat into a single folder
- **Geofencing** — optionally filter predictions by country and US state to improve accuracy in your region
- **Confidence threshold** — tune how certain the model needs to be before filing a result (default 0.4)
- **Sharpest frame selection** — when your camera fires bursts, scores each frame for sharpness and keeps only the clearest one
- **Recursive or top-level scan** — walk the full source folder tree, or scan only the top-level folder
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

### Option A: Windows installer (recommended)

Download `TrailCamSorter-Setup.exe` from the [Releases](../../releases) page and run it. The setup wizard installs the app to Program Files, creates a Start Menu shortcut, and registers an uninstaller. No Python or conda required. Model weights (~1 GB) are downloaded on first run.

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
  --country           ISO 3166-1 alpha-3 code (e.g. USA) — optional geofencing (see Notes)
  --region            US state abbreviation (e.g. VA) — only applies when country=USA
  --move              Move files instead of copying
  --no-subfolders     Put all files flat in the output folder instead of species subfolders
  --no-recursive      Scan only the top-level source folder; ignore subfolders
  --sharpest          Copy only the sharpest frame per burst (blur detection). Videos always included.
  --dry-run           Preview without touching any files
  -v, --verbose       Debug output
```

## File naming convention

Files are accepted in any of these forms — the sorter tries each in order:

1. **Standard trail cam filenames** (fastest, no file reads needed):
   ```
   20240615_083012.jpg      base image
   20240615_083012_1.jpg    burst variant
   20240615_083012_2.jpg    burst variant
   20240615_083012.mp4      video
   ```

2. **Any image with EXIF data** — `DateTimeOriginal` is read directly from the photo metadata. This covers JPEGs straight off an SD card with generic names like `DSCF0001.JPG` or `IMG_20240615_083012.jpg`.

3. **Files with no EXIF** — the file's modification timestamp is used as a fallback. Videos typically fall into this category.

Output files are always renamed to `yyyy-mm-dd_HH-MM-SS_Species Name.ext` regardless of the original filename.

## Notes

- Model weights are cached in `~/.cache/kagglehub/` after the first run
- SpeciesNet covers 2000+ species trained on 65M images (MegaDetector + EfficientNet V2 ensemble)
- On Windows, run inside a `conda activate trailcam` session or use the full Python path
- **Geofencing** (`--country`/`--region`) applies a geographic range prior from wildlife databases. Use ISO 3166-1 alpha-3 codes for country (e.g. `USA`, not `US`) and 2-letter state abbreviations for region (e.g. `VA`, not `US-VA`). Region is only supported for USA. Leaving both blank is safe.
- **Sharpness / blur detection** (`--sharpest`) scores each image in a burst using Laplacian variance and keeps only the highest-scoring frame. Useful for reducing output when your camera fires 3–5 shots per trigger. Videos are always copied regardless of this setting.

## Contributing / Development

### Environment setup

```bash
conda create -n trailcam python=3.11 pip -y
conda activate trailcam
pip install -r requirements.txt
```

### Running tests

```bash
python -m pytest tests/ -v
```

Expected output: all tests pass (currently 21).

### Building the Windows executable and installer

From the project root (requires Inno Setup 6):

```powershell
.\installer\build.ps1
```

Optional parameters:
```powershell
.\installer\build.ps1 -CondaEnv trailcam -InnoExe "C:\path\to\ISCC.exe"
```

Outputs:
- `installer\dist\TrailCamSorter\` — portable folder (~2–3 GB, PyTorch included)
- `installer\Output\TrailCamSorter-Setup.exe` — Windows installer (~207 MB)

### Compatibility

| | Confirmed |
|---|---|
| OS | Windows 10/11 |
| Python | 3.11 |
| GPU | Optional — NVIDIA CUDA auto-detected; CPU fallback always works |
| Model weights | ~1 GB, downloaded once to `%USERPROFILE%\.cache\kagglehub\` |

---

## Troubleshooting

**First run is slow or seems stuck**
The model weights (~1 GB) are downloaded on first run to `%USERPROFILE%\.cache\kagglehub\` (Windows) or `~/.cache/kagglehub/` (Mac/Linux). This is a one-time download. Subsequent runs load from cache and are much faster. The progress bar animates during download and inference — this is normal.

**"Sharpest frame" produces no improvement**
`--sharpest` requires `opencv-python`. If it isn't installed, all sharpness scores will be 0.0 and the first image in each burst will be selected instead. Install it with:
```bash
pip install opencv-python
```

**Files aren't being picked up**
- The sorter accepts `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.mp4`, `.avi`, `.mov`, `.mkv`
- Files with no EXIF and no timestamp in the filename are grouped by modification time — check that file dates weren't reset when copying from your SD card
- Use `--verbose` to see per-file decisions in the log

**Geofencing not working**
Use ISO 3166-1 alpha-3 codes for country (`USA`, not `US`) and 2-letter state abbreviations for region (`VA`, not `Virginia` or `US-VA`). Region only applies when country is `USA`.

**Output goes entirely to `Review/`**
Lower the confidence threshold with `-c 0.2` or `--confidence 0.2`. The default of 0.4 is conservative — results below this threshold are routed to `Review/` for manual inspection.
