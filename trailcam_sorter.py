"""
Trail Cam Sorter - Identify species with Google SpeciesNet and sort files.

Requirements
------------
    pip install speciesnet customtkinter

Hardware: works on CPU; auto-uses NVIDIA GPU when available.

Usage
-----
    python trailcam_sorter.py                        # GUI
    python trailcam_sorter.py "D:\\TrailCam\\June2026"
    python trailcam_sorter.py "D:\\TrailCam\\June2026" --country USA --dry-run
    python trailcam_sorter.py "D:\\TrailCam\\June2026" --confidence 0.5 --move
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

import argparse
import json
import logging
import queue
import re
import shutil
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

COUNTRY_CODES = [
    "", "USA", "AUS", "BRA", "CAN", "CHN", "DEU", "FIN", "FRA",
    "GBR", "IND", "JPN", "KEN", "MEX", "NOR", "NZL", "SWE", "TZA", "ZAF",
]

US_STATES = [
    "", "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE",
    "FL", "GA", "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA",
    "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND",
    "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI",
    "WV", "WY",
]
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
LOG_FMT_SHORT = "%(asctime)s  %(message)s"

CONFIG_PATH = Path.home() / ".trailcam_sorter.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict):
    try:
        existing = load_config()
        existing.update(data)
        CONFIG_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_label(label: str) -> str:
    """Turn a SpeciesNet label into a valid folder/file name.

    Labels look like:  "mammalia;cervidae;odocoileus virginianus"
    We take the most-specific (rightmost) part and title-case it.
    """
    parts = label.split(";")
    name = parts[-1].strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name.strip().title() if name else "Unknown"


def _event_key_from_exif(path: Path) -> Optional[str]:
    """Read DateTimeOriginal (or DateTime) from EXIF and return as YYYYMMDD_HHMMSS."""
    try:
        from PIL import Image
        img = Image.open(path)
        exif = img.getexif()
        dt_str = exif.get(36867) or exif.get(306)   # DateTimeOriginal, then DateTime
        if dt_str:
            dt = datetime.strptime(dt_str.strip(), "%Y:%m:%d %H:%M:%S")
            return dt.strftime("%Y%m%d_%H%M%S")
    except Exception:
        pass
    return None


def _event_key_from_mtime(path: Path) -> str:
    """Fall back to file modification time as YYYYMMDD_HHMMSS."""
    dt = datetime.fromtimestamp(path.stat().st_mtime)
    return dt.strftime("%Y%m%d_%H%M%S")


def group_events(folder: Path, recursive: bool = True) -> dict[str, list[Path]]:
    """Group files by their base timestamp (the 'event key').

    Priority: (1) filename pattern match, (2) EXIF DateTimeOriginal, (3) file mtime.
    Returns {event_key: [file1, file2, ...]} where event_key = "20240615_083012".
    """
    events: dict[str, list[Path]] = defaultdict(list)
    scan = folder.rglob("*") if recursive else folder.glob("*")
    for f in sorted(scan):
        if not f.is_file() or f.suffix.lower() not in ALL_EXTS:
            continue
        m = EVENT_PATTERN.match(f.name)
        if m:
            event_key = m.group(1)
        elif f.suffix.lower() in IMAGE_EXTS:
            event_key = _event_key_from_exif(f) or _event_key_from_mtime(f)
        else:
            event_key = _event_key_from_mtime(f)
        events[event_key].append(f)
    return dict(events)


def pick_representative(files: list[Path], use_sharpness: bool = False) -> Optional[Path]:
    """Choose the single image to classify for this event group.

    With use_sharpness=False (default): base image (no variant suffix) > lowest variant number.
    With use_sharpness=True: returns the image with the highest Laplacian variance score.
    Returns None for video-only groups.
    """
    images = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
    if not images:
        return None

    if use_sharpness and len(images) > 1:
        scored = [(score_sharpness(f), f) for f in images]
        return max(scored, key=lambda x: x[0])[1]

    def sort_key(p: Path):
        m = EVENT_PATTERN.match(p.name)
        variant = int(m.group(2)) if m and m.group(2) else -1
        return variant

    images.sort(key=sort_key)
    return images[0]


def score_sharpness(path: Path) -> float:
    """Return the Laplacian variance of an image as a sharpness score.

    Higher = sharper. Returns 0.0 on any read error or if cv2 is unavailable.
    """
    try:
        import cv2
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0
        return float(cv2.Laplacian(img, cv2.CV_64F).var())
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# SpeciesNet wrapper
# ---------------------------------------------------------------------------

def load_model(log: logging.Logger):
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

    lookup: dict[str, dict] = {}
    for pred in results.get("predictions", []):
        lookup[pred["filepath"]] = pred
    return lookup


# ---------------------------------------------------------------------------
# File mover / copier
# ---------------------------------------------------------------------------

class Cancelled(Exception):
    pass


def sort_files(
    events: dict[str, list[Path]],
    predictions: dict[str, dict],
    rep_map: dict[str, Path],
    dest_root: Path,
    min_confidence: float,
    move: bool,
    dry_run: bool,
    log: logging.Logger,
    subfolders: bool = True,
    sharpness: bool = False,
    progress_callback: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict[str, int]:
    """Copy/move files into species subfolders, renamed to yyyy-mm-dd_HH-MM-SS_species.ext.

    Blank predictions are skipped. Low-confidence/unknown go to Review/.
    Video-only events are matched to classified image events by minute.
    Returns counter {species_folder: count}.
    """
    stats: dict[str, int] = defaultdict(int)
    action = shutil.move if move else shutil.copy2
    verb = "MOVE" if move else "COPY"

    # Build minute-level species lookup (YYYYMMDD_HHMM -> species)
    minute_species: dict[str, str] = {}
    for ek in rep_map:
        pred = predictions.get(str(rep_map[ek]), {})
        lbl = pred.get("prediction", "")
        sc = pred.get("prediction_score", 0.0) or 0.0
        sp = sanitize_label(lbl) if lbl else ""
        if sp and sp.lower() != "blank" and sc >= min_confidence and "unknown" not in lbl.lower():
            minute_species[ek[:13]] = sp

    total_events = len(events)
    for i, (event_key, files) in enumerate(events.items()):
        if cancel_event and cancel_event.is_set():
            raise Cancelled()
        if progress_callback:
            progress_callback(0.85 + 0.15 * (i / max(total_events, 1)))

        rep = rep_map.get(event_key)
        if rep is None:
            species_name = minute_species.get(event_key[:13])
            if not species_name:
                log.debug("Event %s: video-only, no image match within same minute, skipping", event_key)
                continue
            log.debug("Event %s: video matched to '%s' by minute", event_key, species_name)
        else:
            pred = predictions.get(str(rep), {})
            label = pred.get("prediction", "")
            score = pred.get("prediction_score", 0.0) or 0.0
            species_name = sanitize_label(label) if label else ""

            if species_name.lower() == "blank":
                log.debug("Event %s: blank prediction, skipping", event_key)
                continue

            if not label or score < min_confidence \
                    or "unknown" in label.lower() \
                    or species_name.lower() in ("animal", "no cv result"):
                log.debug("Event %s: score %.3f label '%s' -> Review",
                          event_key, score, label)
                species_name = "Review"

        date_str = f"{event_key[:4]}-{event_key[4:6]}-{event_key[6:8]}"
        time_str = f"{event_key[9:11]}-{event_key[11:13]}-{event_key[13:15]}"
        target_dir = dest_root / species_name if subfolders else dest_root

        files_to_copy = (
            [rep_map[event_key]] + [f for f in files if f.suffix.lower() in VIDEO_EXTS]
            if sharpness and rep_map.get(event_key)
            else files
        )

        for f in files_to_copy:
            ext = f.suffix.lower()
            dst = target_dir / f"{date_str}_{time_str}_{species_name}{ext}"
            i2 = 2
            while dst.exists():
                dst = target_dir / f"{date_str}_{time_str}_{species_name}_{i2}{ext}"
                i2 += 1

            if dry_run:
                log.debug("[DRY RUN] %s  %s  ->  %s/%s", verb, f.name, species_name, dst.name)
            else:
                target_dir.mkdir(parents=True, exist_ok=True)
                action(str(f), str(dst))
                log.debug("%s  %s  ->  %s/%s", verb, f.name, species_name, dst.name)

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
# Core processing (called by both GUI and CLI)
# ---------------------------------------------------------------------------

def run_sort(
    source: Path,
    dest_root: Path,
    confidence: float,
    country: Optional[str],
    region: Optional[str],
    move: bool,
    dry_run: bool,
    verbose: bool,
    log: logging.Logger,
    subfolders: bool = True,
    sharpness: bool = False,
    recursive: bool = True,
    progress_callback: Optional[Callable[[float], None]] = None,
    status_callback: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
):
    """Run the full sort pipeline. Raises Cancelled if cancel_event is set."""
    def check():
        if cancel_event and cancel_event.is_set():
            raise Cancelled()

    def status(msg: str):
        if status_callback:
            status_callback(msg)

    if progress_callback:
        progress_callback(0.0)

    log.info("Source : %s", source)
    log.info("Output : %s", dest_root)
    log.info("Mode   : %s", "MOVE" if move else "COPY")
    if dry_run:
        log.info("*** DRY RUN -- no files will be touched ***")

    # 1. Group files by event
    check()
    status("Scanning files…")
    events = group_events(source, recursive=recursive)
    if not events:
        log.warning("No matching files found in %s", source)
        return

    total_files = sum(len(v) for v in events.values())
    log.info("Found %d events encompassing %d files", len(events), total_files)
    if progress_callback:
        progress_callback(0.05)

    # 2. Pick representative images
    check()
    rep_map: dict[str, Path] = {}
    images_to_classify: list[Path] = []
    for event_key, files in events.items():
        rep = pick_representative(files, use_sharpness=sharpness)
        if rep:
            rep_map[event_key] = rep
            images_to_classify.append(rep)

    video_only = len(events) - len(rep_map)
    log.info("Will classify %d representative images (%d video-only events)",
             len(images_to_classify), video_only)

    if not images_to_classify:
        log.warning("No images to classify -- nothing to do.")
        return

    if progress_callback:
        progress_callback(0.10)

    # 3. Load model & run inference (cannot be interrupted mid-inference)
    status("Loading model…")
    model = load_model(log)
    if progress_callback:
        progress_callback(0.20)

    status(f"Running inference on {len(images_to_classify)} images…")
    predictions = classify_images(model, images_to_classify, country, region, log)
    if progress_callback:
        progress_callback(0.85)

    check()  # honour cancel after inference completes

    species_seen: dict[str, int] = defaultdict(int)
    for pred in predictions.values():
        lbl = pred.get("prediction", "unknown")
        species_seen[sanitize_label(lbl)] += 1
    log.info("Species detected: %s",
             ", ".join(f"{k} ({v})" for k, v in
                       sorted(species_seen.items(), key=lambda x: -x[1])))

    # 4. Sort files
    status("Copying files…" if not dry_run else "Previewing (dry run)…")
    stats = sort_files(
        events, predictions, rep_map,
        dest_root, confidence, move, dry_run, log,
        subfolders=subfolders,
        sharpness=sharpness,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
    )

    # 5. Write report
    if not dry_run:
        write_report(dest_root, events, predictions, rep_map, stats, log)

    # Summary
    total_sorted = sum(stats.values())
    log.info("")
    log.info("=== SORTING COMPLETE ===")
    log.info("%-36s  %5s", "Species / Category", "Files")
    log.info("%-36s  %5s", "-" * 36, "-----")
    for species, count in sorted(stats.items(), key=lambda x: -x[1]):
        log.info("%-36s  %5d", species, count)
    log.info("%-36s  %5d", "TOTAL", total_sorted)
    log.info("")
    log.info("Output: %s", dest_root)

    status(f"Complete — {total_sorted} file{'s' if total_sorted != 1 else ''} sorted")
    if progress_callback:
        progress_callback(1.0)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    """Logging handler that pushes formatted records into a queue."""
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(("log", self.format(record)))


class TrailCamGUI:
    def __init__(self):
        import customtkinter as ctk
        self.ctk = ctk

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("TrailCam Sorter")
        self.root.geometry("820x790")
        self.root.resizable(True, True)
        self.root.minsize(680, 580)
        self.root.configure(fg_color="#161c24")

        self._q: queue.Queue = queue.Queue()
        self._running = False
        self._busy = False
        self._anim_tick = 0.0
        self._cancel_event = threading.Event()

        self._build_ui()

    def _build_ui(self):
        ctk = self.ctk

        BG       = "#161c24"
        CARD     = "#1e2736"
        INNER    = "#232f40"
        HDR      = "#0d1a10"
        GREEN    = "#2d7d52"
        GREEN_H  = "#37965f"
        CANCEL   = "#7a2222"
        CANCEL_H = "#5a1818"
        CLOSE_H  = "#2d3d50"
        TEXT     = "#c8d8e8"
        DIM      = "#6a8090"
        MUTED    = "#4a6070"
        SEP      = "#2a3a4a"

        def section_header(text: str):
            row = ctk.CTkFrame(self.root, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(10, 0))
            ctk.CTkLabel(
                row, text=text,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                text_color=MUTED,
            ).pack(side="left")
            ctk.CTkFrame(row, height=1, fg_color=SEP).pack(
                side="left", fill="x", expand=True, padx=(8, 0)
            )

        # ── Header ───────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self.root, corner_radius=0, fg_color=HDR)
        hdr.pack(fill="x")
        hdr_inner = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_inner.pack(fill="x", padx=20, pady=(16, 14))
        ctk.CTkLabel(
            hdr_inner,
            text="TrailCam Sorter",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#c8e8d0",
        ).pack(side="left")
        ctk.CTkLabel(
            hdr_inner,
            text="  ·  AI-powered species identification via Google SpeciesNet",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#3a6050",
        ).pack(side="left", pady=(3, 0))

        # ── Folders ──────────────────────────────────────────────────────
        section_header("INPUT / OUTPUT")
        folders = ctk.CTkFrame(self.root, fg_color=CARD, corner_radius=8)
        folders.pack(fill="x", padx=16, pady=(6, 0))
        folders.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            folders, text="Source",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=DIM, width=64, anchor="w",
        ).grid(row=0, column=0, padx=(16, 6), pady=(16, 6), sticky="w")
        self.src_var = ctk.StringVar()
        ctk.CTkEntry(
            folders, textvariable=self.src_var,
            placeholder_text="Select the folder containing trail-cam files…",
            fg_color=INNER, border_color=SEP, border_width=1,
        ).grid(row=0, column=1, padx=4, pady=(16, 6), sticky="ew")
        ctk.CTkButton(
            folders, text="Browse", width=80,
            fg_color=INNER, hover_color=CLOSE_H,
            border_width=1, border_color=SEP,
            font=ctk.CTkFont(size=12), text_color=DIM,
            command=lambda: self._browse(self.src_var, "Select trail-cam folder"),
        ).grid(row=0, column=2, padx=(4, 16), pady=(16, 6))

        ctk.CTkLabel(
            folders, text="Output",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=DIM, width=64, anchor="w",
        ).grid(row=1, column=0, padx=(16, 6), pady=(6, 16), sticky="w")
        default_out = load_config().get("last_output", str(Path.home() / "TrailCamAnimals"))
        self.out_var = ctk.StringVar(value=default_out)
        ctk.CTkEntry(
            folders, textvariable=self.out_var,
            fg_color=INNER, border_color=SEP, border_width=1,
        ).grid(row=1, column=1, padx=4, pady=(6, 16), sticky="ew")
        ctk.CTkButton(
            folders, text="Browse", width=80,
            fg_color=INNER, hover_color=CLOSE_H,
            border_width=1, border_color=SEP,
            font=ctk.CTkFont(size=12), text_color=DIM,
            command=lambda: self._browse(self.out_var, "Select output folder"),
        ).grid(row=1, column=2, padx=(4, 16), pady=(6, 16))

        # ── Options ──────────────────────────────────────────────────────
        section_header("OPTIONS")
        opts = ctk.CTkFrame(self.root, fg_color=CARD, corner_radius=8)
        opts.pack(fill="x", padx=16, pady=(6, 0))

        geo_row = ctk.CTkFrame(opts, fg_color="transparent")
        geo_row.pack(fill="x", padx=16, pady=(14, 4))

        ctk.CTkLabel(geo_row, text="Country",
                     font=ctk.CTkFont(size=11), text_color=DIM).pack(side="left", padx=(0, 6))
        self.country_var = ctk.StringVar(value="")
        self.country_combo = ctk.CTkComboBox(
            geo_row, variable=self.country_var, width=96, values=COUNTRY_CODES,
            fg_color=INNER, border_color=SEP, button_color=SEP, button_hover_color=CLOSE_H,
            dropdown_fg_color=INNER, dropdown_hover_color=CLOSE_H, dropdown_text_color=TEXT,
            command=self._on_country_change,
        )
        self.country_combo.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(geo_row, text="Region (US)",
                     font=ctk.CTkFont(size=11), text_color=DIM).pack(side="left", padx=(0, 6))
        self.region_var = ctk.StringVar(value="")
        self.region_combo = ctk.CTkComboBox(
            geo_row, variable=self.region_var, width=86, values=US_STATES, state="disabled",
            fg_color=INNER, border_color=SEP, button_color=SEP, button_hover_color=CLOSE_H,
            dropdown_fg_color=INNER, dropdown_hover_color=CLOSE_H, dropdown_text_color=TEXT,
        )
        self.region_combo.pack(side="left", padx=(0, 28))

        ctk.CTkLabel(geo_row, text="Confidence",
                     font=ctk.CTkFont(size=11), text_color=DIM).pack(side="left", padx=(0, 8))
        self.conf_var = ctk.DoubleVar(value=0.4)
        ctk.CTkSlider(
            geo_row, from_=0.1, to=0.9, number_of_steps=16,
            variable=self.conf_var, width=140,
            button_color=GREEN, button_hover_color=GREEN_H, progress_color=GREEN,
            fg_color=INNER,
            command=lambda v: self.conf_label.configure(text=f"{float(v):.2f}"),
        ).pack(side="left")
        self.conf_label = ctk.CTkLabel(
            geo_row, text="0.40", width=40,
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
        )
        self.conf_label.pack(side="left", padx=(6, 0))

        ctk.CTkLabel(
            opts,
            text="Geofencing optional · Region for USA only  ·  "
                 "Confidence: 0.4 default, lower = more results, higher = more certain",
            font=ctk.CTkFont(size=10), text_color=MUTED, anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkFrame(opts, height=1, fg_color=SEP).pack(fill="x", padx=12, pady=(0, 10))

        chk_row = ctk.CTkFrame(opts, fg_color="transparent")
        chk_row.pack(fill="x", padx=16, pady=(0, 14))

        self.recursive_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            chk_row, text="Scan subfolders", variable=self.recursive_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(0, 22))

        self.move_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            chk_row, text="Move files", variable=self.move_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(0, 22))

        self.subfolders_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            chk_row, text="Species subfolders", variable=self.subfolders_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(0, 22))

        self.dry_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            chk_row, text="Dry run", variable=self.dry_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(0, 22))

        self.sharpness_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            chk_row, text="Pick sharpest frame", variable=self.sharpness_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left")

        # ── Run controls ─────────────────────────────────────────────────
        section_header("RUN")
        run_card = ctk.CTkFrame(self.root, fg_color=CARD, corner_radius=8)
        run_card.pack(fill="x", padx=16, pady=(6, 0))

        btn_row = ctk.CTkFrame(run_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(14, 8))
        btn_row.columnconfigure(0, weight=1)

        self.run_btn = ctk.CTkButton(
            btn_row, text="▶  Run Sort", height=44,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color=GREEN, hover_color=GREEN_H, text_color="white",
            command=self._on_run,
        )
        self.run_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", height=44, width=100,
            fg_color=CANCEL, hover_color=CANCEL_H,
            font=ctk.CTkFont(size=13), state="disabled",
            command=self._on_cancel,
        )
        self.cancel_btn.grid(row=0, column=1, padx=(0, 8))

        self.close_btn = ctk.CTkButton(
            btn_row, text="Close", height=44, width=86,
            fg_color=INNER, hover_color=CLOSE_H,
            border_width=1, border_color=SEP,
            font=ctk.CTkFont(size=13), text_color=DIM,
            command=self.root.destroy,
        )
        self.close_btn.grid(row=0, column=2)

        prog_row = ctk.CTkFrame(run_card, fg_color="transparent")
        prog_row.pack(fill="x", padx=14, pady=(0, 6))
        prog_row.columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(
            prog_row, height=8,
            fg_color=INNER, progress_color=GREEN,
        )
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.progress.set(0)

        self.pct_label = ctk.CTkLabel(
            prog_row, text="", width=42,
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
        )
        self.pct_label.grid(row=0, column=1)

        self.status_label = ctk.CTkLabel(
            run_card, text="",
            font=ctk.CTkFont(size=11), text_color=DIM, anchor="w",
        )
        self.status_label.pack(anchor="w", padx=14, pady=(2, 12))

        # ── Activity log ─────────────────────────────────────────────────
        section_header("ACTIVITY LOG")
        self.log_box = ctk.CTkTextbox(
            self.root,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=CARD,
            text_color="#6aab85",
            border_color=SEP, border_width=1,
            scrollbar_button_color=SEP,
            scrollbar_button_hover_color=GREEN,
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(6, 16))

    def _on_country_change(self, value: str):
        if value == "USA":
            self.region_combo.configure(state="normal")
        else:
            self.region_var.set("")
            self.region_combo.configure(state="disabled")

    def _browse(self, var, title: str):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title=title, parent=self.root)
        if folder:
            var.set(str(Path(folder)))

    def _set_progress(self, value: float):
        self._busy = False
        self.progress.set(value)
        self.pct_label.configure(text=f"{int(value * 100)}%")

    def _append_log(self, msg: str):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    def _poll(self):
        import math
        try:
            while True:
                kind, value = self._q.get_nowait()
                if kind == "log":
                    self._append_log(value)
                elif kind == "progress":
                    self._set_progress(value)
                elif kind == "status":
                    self.status_label.configure(text=value)
                    # Switch to animated bar during model load and inference
                    busy = any(k in value for k in ("Loading model", "Running inference"))
                    self._busy = busy
                    if busy:
                        self.pct_label.configure(text="")
                elif kind == "done":
                    self._set_progress(1.0 if value == "ok" else self.progress.get())
                    self.run_btn.configure(state="normal", text="Run")
                    self.cancel_btn.configure(state="disabled")
                    self.close_btn.configure(state="normal")
                    self._running = False
                    return
        except queue.Empty:
            pass
        # Animate progress bar during busy (indeterminate) phases
        if self._busy:
            self._anim_tick += 0.12
            self.progress.set(0.5 + 0.42 * math.sin(self._anim_tick))
        if self._running:
            self.root.after(100, self._poll)

    def _on_cancel(self):
        self._cancel_event.set()
        self.cancel_btn.configure(state="disabled", text="Cancelling…")
        self._append_log("Cancelling — will stop after current operation...")
        if self._busy:
            self.status_label.configure(
                text="Waiting for inference to finish before cancelling…"
            )

    def _on_run(self):
        if self._running:
            return

        src_str = self.src_var.get().strip()
        if not src_str:
            self._append_log("Please select a source folder first.")
            return
        source = Path(src_str)
        if not source.is_dir():
            self._append_log(f"Folder not found: {source}")
            return

        self.log_box.delete("1.0", "end")
        self._set_progress(0)
        self.pct_label.configure(text="")
        self.status_label.configure(text="")
        self._cancel_event.clear()
        self.run_btn.configure(state="disabled", text="Running…")
        self.cancel_btn.configure(state="normal", text="Cancel")
        self.close_btn.configure(state="disabled")
        self._running = True
        self.root.after(100, self._poll)

        log = logging.getLogger("trailcam_gui")
        log.setLevel(logging.DEBUG)
        log.handlers.clear()
        handler = _QueueHandler(self._q)
        handler.setFormatter(logging.Formatter(LOG_FMT_SHORT))
        log.addHandler(handler)

        dest_root = Path(self.out_var.get().strip()).resolve()
        country = self.country_var.get().strip() or None
        region = self.region_var.get().strip() or None

        def worker():
            try:
                run_sort(
                    source=source.resolve(),
                    dest_root=dest_root,
                    confidence=self.conf_var.get(),
                    country=country,
                    region=region,
                    move=self.move_var.get(),
                    dry_run=self.dry_var.get(),
                    verbose=False,
                    log=log,
                    subfolders=self.subfolders_var.get(),
                    sharpness=self.sharpness_var.get(),
                    recursive=self.recursive_var.get(),
                    progress_callback=lambda v: self._q.put(("progress", v)),
                    status_callback=lambda s: self._q.put(("status", s)),
                    cancel_event=self._cancel_event,
                )
                save_config({"last_output": str(dest_root)})
                self._q.put(("done", "ok"))
            except Cancelled:
                self._q.put(("log", "Run cancelled."))
                self._q.put(("done", "cancelled"))
            except Exception as exc:
                log.error("Unexpected error: %s", exc)
                self._q.put(("done", "error"))

        threading.Thread(target=worker, daemon=True).start()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    # No arguments → launch GUI
    if len(sys.argv) == 1:
        TrailCamGUI().run()
        return

    parser = argparse.ArgumentParser(
        description="Sort trail-cam photos & videos into species subfolders "
                    "using Google SpeciesNet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="Folder containing trail-cam images/videos.")
    parser.add_argument("-o", "--output", default=str(Path.home() / "TrailCamAnimals"),
                        help="Destination root.  Default: ~/TrailCamAnimals")
    parser.add_argument("-c", "--confidence", type=float, default=0.4,
                        help="Minimum confidence threshold (0-1).  Default: 0.4")
    parser.add_argument("--country", default=None,
                        help="ISO 3166-1 alpha-3 country code (e.g. USA)")
    parser.add_argument("--region", default=None,
                        help="US state abbreviation (e.g. VA) — only applies when country=USA")
    parser.add_argument("--move", action="store_true",
                        help="Move files instead of copying.")
    parser.add_argument("--no-subfolders", action="store_true",
                        help="Put all files flat in the output folder instead of species subfolders.")
    parser.add_argument("--no-recursive", action="store_true",
                        help="Scan only the top-level source folder; ignore subfolders.")
    parser.add_argument("--sharpest", action="store_true",
                        help="Score burst images for sharpness and copy only the sharpest frame. "
                             "Videos are always included. Default: off.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without touching files.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(format=LOG_FMT, level=level, stream=sys.stdout)
    log = logging.getLogger("trailcam_sorter")

    source = Path(args.source).resolve()
    if not source.is_dir():
        log.error("Source folder not found: %s", source)
        sys.exit(1)

    run_sort(
        source=source,
        dest_root=Path(args.output).resolve(),
        confidence=args.confidence,
        country=args.country,
        region=args.region,
        move=args.move,
        dry_run=args.dry_run,
        verbose=args.verbose,
        log=log,
        subfolders=not args.no_subfolders,
        sharpness=args.sharpest,
        recursive=not args.no_recursive,
    )


if __name__ == "__main__":
    main()
