"""
Trail Cam Sorter - Identify species with Google SpeciesNet and sort files.

Requirements
------------
    pip install speciesnet

Hardware: works on CPU; auto-uses NVIDIA GPU when available.

Usage
-----
    python trailcam_sorter.py "D:\\TrailCam\\June2026"
    python trailcam_sorter.py "D:\\TrailCam\\June2026" --country US --dry-run
    python trailcam_sorter.py "D:\\TrailCam\\June2026" --confidence 0.5 --move
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv"}
ALL_EXTS = IMAGE_EXTS | VIDEO_EXTS

# Matches: 20240615_083012.jpg, 20240615_083012_1.jpg, 20240615_083012_2.mp4
EVENT_PATTERN = re.compile(
    r"^(\d{8}_\d{6})"       # base timestamp  (group 1)
    r"(?:_(\d+))?"           # optional variant (group 2)
    r"(\.\w+)$",             # extension        (group 3)
    re.IGNORECASE,
)

LOG_FMT = "%(asctime)s  %(levelname)-8s  %(message)s"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pick_folder(title: str) -> Optional[Path]:
    """Show a native folder-picker dialog; return chosen Path or None."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    folder = filedialog.askdirectory(title=title)
    root.destroy()
    return Path(folder) if folder else None


def setup_logging(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format=LOG_FMT, level=level, stream=sys.stdout)
    return logging.getLogger("trailcam_sorter")


def sanitize_label(label: str) -> str:
    """Turn a SpeciesNet label into a valid folder name.

    Labels look like:  "mammalia;cervidae;odocoileus virginianus"
    We take the most-specific (rightmost) part and title-case it.
    """
    parts = label.split(";")
    name = parts[-1].strip()
    # Replace characters that are illegal in Windows folder names
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name.strip().title() if name else "Unknown"


def group_events(folder: Path) -> dict[str, list[Path]]:
    """Group files by their base timestamp (the 'event key').

    Returns {event_key: [file1, file2, ...]} where event_key = "20240615_083012".
    """
    events: dict[str, list[Path]] = defaultdict(list)
    for f in sorted(folder.rglob("*")):
        if not f.is_file():
            continue
        m = EVENT_PATTERN.match(f.name)
        if m and f.suffix.lower() in ALL_EXTS:
            events[m.group(1)].append(f)
    return dict(events)



def pick_representative(files: list[Path]) -> Optional[Path]:
    """Choose the single image to classify for this event group.

    Priority: base image (no variant suffix) > lowest variant number.
    Skips video-only groups (returns None).
    """
    images = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
    if not images:
        return None

    def sort_key(p: Path):
        m = EVENT_PATTERN.match(p.name)
        variant = int(m.group(2)) if m and m.group(2) else -1
        return variant

    images.sort(key=sort_key)
    return images[0]


# ---------------------------------------------------------------------------
# SpeciesNet wrapper
# ---------------------------------------------------------------------------

def load_model(log: logging.Logger):
    """Import and instantiate SpeciesNet once."""
    log.info("Loading SpeciesNet model (first run downloads ~1 GB of weights)...")
    t0 = time.time()

    from speciesnet import DEFAULT_MODEL, SpeciesNet
    model = SpeciesNet(DEFAULT_MODEL)
    log.info("Model ready in %.1f s", time.time() - t0)
    return model


def classify_images(
    model,
    image_paths: list[Path],
    country: Optional[str],
    region: Optional[str],
    log: logging.Logger,
) -> dict[str, dict]:
    """Run SpeciesNet on a batch of representative images.

    Returns {filepath_str: prediction_record, ...}
    """
    instances = [{"filepath": str(p)} for p in image_paths]
    instances_dict = {"instances": instances}

    log.info("Running SpeciesNet on %d images...", len(instances))
    t0 = time.time()
    kwargs: dict = {"instances_dict": instances_dict}
    if country:
        kwargs["country"] = country
    if region:
        kwargs["admin1_region"] = region
    results = model.predict(**kwargs)
    elapsed = time.time() - t0
    log.info("Inference done in %.1f s  (%.2f s/image)",
             elapsed, elapsed / max(len(instances), 1))

    # Build lookup by filepath
    lookup: dict[str, dict] = {}
    for pred in results.get("predictions", []):
        lookup[pred["filepath"]] = pred
    return lookup


# ---------------------------------------------------------------------------
# File mover / copier
# ---------------------------------------------------------------------------

def sort_files(
    events: dict[str, list[Path]],
    predictions: dict[str, dict],
    rep_map: dict[str, Path],
    dest_root: Path,
    min_confidence: float,
    move: bool,
    dry_run: bool,
    log: logging.Logger,
) -> dict[str, int]:
    """Copy/move files into species subfolders, renamed to yyyy-mm-dd_species.ext.

    Skips video-only events and events below the confidence threshold.
    Returns counter {species_folder: count}.
    """
    stats: dict[str, int] = defaultdict(int)
    action = shutil.move if move else shutil.copy2
    verb = "MOVE" if move else "COPY"

    # Build minute-level species lookup from classified image events (YYYYMMDD_HHMM -> species)
    minute_species: dict[str, str] = {}
    for ek in rep_map:
        pred = predictions.get(str(rep_map[ek]), {})
        lbl = pred.get("prediction", "")
        sc = pred.get("prediction_score", 0.0) or 0.0
        sp = sanitize_label(lbl) if lbl else ""
        if sp and sp.lower() != "blank" and sc >= min_confidence and "unknown" not in lbl.lower():
            minute_species[ek[:13]] = sp

    for event_key, files in events.items():
        rep = rep_map.get(event_key)
        if rep is None:
            # Video-only: match to a classified image event in the same minute
            species_name = minute_species.get(event_key[:13])
            if not species_name:
                log.debug("Event %s: video-only, no image match within same minute, skipping", event_key)
                continue
            log.debug("Event %s: video matched to '%s' by minute", event_key, species_name)
            date_str = f"{event_key[:4]}-{event_key[4:6]}-{event_key[6:8]}"
            target_dir = dest_root / species_name
            for f in files:
                ext = f.suffix.lower()
                dst = target_dir / f"{date_str}_{species_name}{ext}"
                i = 2
                while dst.exists():
                    dst = target_dir / f"{date_str}_{species_name}_{i}{ext}"
                    i += 1
                if dry_run:
                    log.info("[DRY RUN] %s  %s  ->  %s/%s", verb, f.name, species_name, dst.name)
                else:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    action(str(f), str(dst))
                    log.info("%s  %s  ->  %s/%s", verb, f.name, species_name, dst.name)
                stats[species_name] += 1
            continue

        pred = predictions.get(str(rep), {})
        label = pred.get("prediction", "")
        score = pred.get("prediction_score", 0.0) or 0.0

        species_name = sanitize_label(label) if label else ""

        if species_name.lower() == "blank":
            log.debug("Event %s: blank prediction, skipping", event_key)
            continue

        if not label or score < min_confidence or "unknown" in label.lower():
            log.debug("Event %s: score %.3f label '%s' -> Review",
                      event_key, score, label)
            species_name = "Review"

        date_str = f"{event_key[:4]}-{event_key[4:6]}-{event_key[6:8]}"
        target_dir = dest_root / species_name

        for f in files:
            ext = f.suffix.lower()
            dst = target_dir / f"{date_str}_{species_name}{ext}"
            i = 2
            while dst.exists():
                dst = target_dir / f"{date_str}_{species_name}_{i}{ext}"
                i += 1

            if dry_run:
                log.info("[DRY RUN] %s  %s  ->  %s/%s", verb, f.name, species_name, dst.name)
            else:
                target_dir.mkdir(parents=True, exist_ok=True)
                action(str(f), str(dst))
                log.info("%s  %s  ->  %s/%s", verb, f.name, species_name, dst.name)

            stats[species_name] += 1

    return dict(stats)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    dest_root: Path,
    events: dict[str, list[Path]],
    predictions: dict[str, dict],
    rep_map: dict[str, Path],
    stats: dict[str, int],
    log: logging.Logger,
):
    """Write a JSON report alongside the sorted folders."""
    report = {
        "generated": datetime.now().isoformat(),
        "total_events": len(events),
        "total_files_sorted": sum(stats.values()),
        "species_counts": dict(sorted(stats.items(), key=lambda x: -x[1])),
        "event_details": [],
    }

    for event_key, files in sorted(events.items()):
        rep = rep_map.get(event_key)
        pred = predictions.get(str(rep), {}) if rep else {}
        report["event_details"].append({
            "event": event_key,
            "representative_image": rep.name if rep else None,
            "prediction": pred.get("prediction", ""),
            "confidence": pred.get("prediction_score", 0.0),
            "files": [f.name for f in files],
        })

    report_path = dest_root / "_sort_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Report saved to %s", report_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sort trail-cam photos & videos into species subfolders "
                    "using Google SpeciesNet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Folder containing trail-cam images and videos.  "
             "Omit to open a folder picker.",
    )
    parser.add_argument(
        "-o", "--output",
        default=str(Path.home() / "TrailCamAnimals"),
        help="Destination root for sorted subfolders.  "
             "Default: ~/TrailCamAnimals",
    )
    parser.add_argument(
        "-c", "--confidence",
        type=float, default=0.4,
        help="Minimum confidence threshold (0-1).  Default: 0.4",
    )
    parser.add_argument(
        "--country",
        default=None,
        help="ISO 3166-1 alpha-2 country code (e.g. US) to improve accuracy "
             "via SpeciesNet geofencing.",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="Admin1 region / state code (e.g. US-VA) for finer geofencing.",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Move files instead of copying (saves disk space).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without touching any files.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show debug-level output.",
    )
    args = parser.parse_args()

    log = setup_logging(args.verbose)

    # ------------------------------------------------------------------
    if args.source:
        source = Path(args.source).resolve()
    else:
        chosen = pick_folder("Select trail-cam folder")
        if not chosen:
            log.error("No folder selected — exiting.")
            sys.exit(1)
        source = chosen.resolve()

    if not source.is_dir():
        log.error("Source folder not found: %s", source)
        sys.exit(1)

    dest_root = Path(args.output).resolve()
    log.info("Source : %s", source)
    log.info("Output : %s", dest_root)
    log.info("Mode   : %s", "MOVE" if args.move else "COPY")
    if args.dry_run:
        log.info("*** DRY RUN -- no files will be touched ***")

    # ------------------------------------------------------------------
    # 1. Group files by event
    # ------------------------------------------------------------------
    events = group_events(source)
    if not events:
        log.warning("No matching files found in %s", source)
        sys.exit(0)

    total_files = sum(len(v) for v in events.values())
    log.info("Found %d events encompassing %d files", len(events), total_files)

    # ------------------------------------------------------------------
    # 2. Pick one representative image per event
    # ------------------------------------------------------------------
    rep_map: dict[str, Path] = {}          # event_key -> representative image
    images_to_classify: list[Path] = []

    for event_key, files in events.items():
        rep = pick_representative(files)
        if rep:
            rep_map[event_key] = rep
            images_to_classify.append(rep)

    video_only = len(events) - len(rep_map)
    log.info("Will classify %d representative images (%d video-only events)",
             len(images_to_classify), video_only)

    if not images_to_classify:
        log.warning("No images to classify -- nothing to do.")
        sys.exit(0)

    # ------------------------------------------------------------------
    # 3. Load model & run inference
    # ------------------------------------------------------------------
    model = load_model(log)
    predictions = classify_images(
        model, images_to_classify, args.country, args.region, log,
    )

    # Quick summary
    species_seen: dict[str, int] = defaultdict(int)
    for pred in predictions.values():
        lbl = pred.get("prediction", "unknown")
        species_seen[sanitize_label(lbl)] += 1
    log.info("Species detected: %s",
             ", ".join(f"{k} ({v})" for k, v in
                       sorted(species_seen.items(), key=lambda x: -x[1])))

    # ------------------------------------------------------------------
    # 4. Sort files into subfolders
    # ------------------------------------------------------------------
    stats = sort_files(
        events, predictions, rep_map,
        dest_root, args.confidence, args.move, args.dry_run, log,
    )

    # ------------------------------------------------------------------
    # 5. Write report
    # ------------------------------------------------------------------
    if not args.dry_run:
        write_report(dest_root, events, predictions, rep_map, stats, log)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    log.info("")
    log.info("=== SORTING COMPLETE ===")
    log.info("%-40s  %s", "Species / Category", "Files")
    log.info("%-40s  %s", "-" * 40, "-----")
    for species, count in sorted(stats.items(), key=lambda x: -x[1]):
        log.info("%-40s  %d", species, count)
    log.info("%-40s  %d", "TOTAL", sum(stats.values()))


if __name__ == "__main__":
    main()
