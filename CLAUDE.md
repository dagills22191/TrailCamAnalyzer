# Trail Cam Sorter

## What this is
A Python script (`trailcam_sorter.py`) that uses Google SpeciesNet to identify species in trail camera images and sort all files into species-named subfolders.

## Hardware
- Windows 11, i7-1165G7, 16GB RAM, NVIDIA MX350 2GB
- MX350 is too small for SpeciesNet GPU — runs on CPU (~1-3 sec/image), which is fine

## Key design decisions
- Uses `pip install speciesnet` (Google's SpeciesNet v5.x) — ensemble of MegaDetector + EfficientNet V2 classifier, 2000+ species, trained on 65M images
- Python API: `from speciesnet import SpeciesNet` → `model = SpeciesNet()` → `model.predict(instances_dict)`
- `instances_dict` format: `{"instances": [{"filepath": "...", "country": "US", "admin1_region": "US-VA"}]}`
- Output has `prediction` (semicolon-delimited taxonomy like `mammalia;cervidae;odocoileus virginianus`) and `prediction_score` (0-1 float)

## File naming convention
Trail cam files follow: `YYYYMMDD_HHMMSS.jpg` with `_1`, `_2`, `_3` variants and matching `.mp4` files per trigger event. Example:
```
20240615_083012.jpg      ← base image (classified)
20240615_083012_1.jpg    ← variant (gets same label)
20240615_083012_2.jpg    ← variant
20240615_083012.mp4      ← video (gets same label)
```
Only one image per event group is classified to save time. Result applies to all files sharing that timestamp.

## Setup (not yet done)
```powershell
conda create -n trailcam python=3.11 pip -y
conda activate trailcam
pip install speciesnet
```

## Usage
```powershell
python trailcam_sorter.py "D:\TrailCam\June2026" --dry-run
python trailcam_sorter.py "D:\TrailCam\June2026" --country US --region US-VA
python trailcam_sorter.py "D:\TrailCam\June2026" --move --confidence 0.6
```

## Output structure
Files are copied (or moved with `--move`) into `<source>/Sorted/<Species Name>/`. A `_sort_report.json` with full event details is written alongside.

## Status
- [x] Script written (`trailcam_sorter.py`)
- [x] Conda environment created (C:\Users\tim\miniconda3\envs\trailcam, Python 3.11)
- [x] speciesnet installed (v5.0.4)
- [ ] Tested on real images
