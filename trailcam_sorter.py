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
    python trailcam_sorter.py "D:\\TrailCam\\June2026" --use-exif-timestamps
    python trailcam_sorter.py "D:\\TrailCam\\June2026" --confidence 0.5 --move
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

import argparse
import csv
import hashlib
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

__version__ = "1.1.1"

# Amber accent used to signal a pending cancel (progress bar + status text).
WARN_AMBER = "#d4912f"
# Red accent used for the error banner on the summary card.
ERROR_RED = "#c0392b"

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
VIDEO_MATCH_MAX_GAP_SECONDS = 60
VIDEO_MATCH_MODES = ("nearest", "minute")
CLASSIFIER_BACKENDS = ("speciesnet",)
EXIF_DATETIME_TAGS = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")
EVENT_KEY_SOURCE_FILENAME = "filename"
EVENT_KEY_SOURCE_EXIF = "exif"
EVENT_KEY_SOURCE_MTIME = "mtime"
CONFIDENCE_PROFILES = {
    "conservative": 0.60,
    "balanced": 0.40,
    "recall": 0.25,
}

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
INFERENCE_BATCH_SIZE = 50


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

def _as_bool(value, default: bool) -> bool:
    """Coerce a possibly hand-edited/legacy config value to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def resolve_startup_settings(config: dict) -> dict:
    """Map a loaded config dict to concrete GUI field values.

    Applies defaults for missing keys, forces move/dry_run off, clamps
    confidence into the slider's 0.1-0.9 range, and clears region when
    country is not USA. Returns a dict keyed by the persisted config-key
    names, plus ``move`` and ``dry_run`` set to False so the GUI can
    initialize every var from one dict.
    """
    config = config if isinstance(config, dict) else {}

    try:
        confidence = float(config.get("confidence", 0.4))
        confidence = min(0.9, max(0.1, confidence))
    except (TypeError, ValueError):
        confidence = 0.4

    country = str(config.get("country", "") or "")
    region = str(config.get("region", "") or "")
    if country != "USA":
        region = ""

    return {
        "last_source": str(config.get("last_source", "") or ""),
        "last_output": str(config.get("last_output")
                           or (Path.home() / "TrailCamAnimals")),
        "advanced_mode": _as_bool(config.get("advanced_mode"), False),
        "recursive": _as_bool(config.get("recursive"), True),
        "country": country,
        "region": region,
        "confidence": confidence,
        "species_subfolders": _as_bool(config.get("species_subfolders"), True),
        "sharpness": _as_bool(config.get("sharpness"), False),
        "exif_fallback": _as_bool(config.get("exif_fallback"), True),
        # Action toggles always start in the safe state, never persisted.
        "move": False,
        "dry_run": False,
    }


def display_path(p: str) -> str:
    """Normalize a path string to native separators for display in the GUI.

    The file dialog returns forward slashes on Windows while config-derived
    defaults use backslashes; normalizing keeps the Source/Output fields
    consistent. Empty strings pass through unchanged.
    """
    return os.path.normpath(p) if p else p


def load_checkpoint(checkpoint_path: Path) -> set[str]:
    """Load completed event keys from a checkpoint file."""
    if not checkpoint_path.is_file():
        return set()
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        keys = payload.get("completed_event_keys", []) if isinstance(payload, dict) else []
        return {str(k) for k in keys}
    except Exception:
        return set()


def save_checkpoint(checkpoint_path: Path, event_keys: set[str]):
    """Persist completed event keys to a checkpoint file."""
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": datetime.now().isoformat(),
        "completed_event_keys": sorted(event_keys),
        "count": len(event_keys),
    }
    checkpoint_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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


def read_exif_datetime(path: Path) -> Optional[datetime]:
    """Read image capture time from EXIF metadata, if present."""
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None

            for tag_id, value in exif.items():
                tag_name = TAGS.get(tag_id, str(tag_id))
                if tag_name in EXIF_DATETIME_TAGS and isinstance(value, str):
                    text = value.strip()
                    try:
                        return datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        continue
    except Exception:
        return None
    return None


def event_key_and_source_for_file(
    path: Path,
    use_exif_timestamps: bool = False,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve a file to an event key and source type.

    Returns (event_key, source) where source is one of: filename, exif, mtime.
    """
    m = EVENT_PATTERN.match(path.name)
    if m and path.suffix.lower() in ALL_EXTS:
        return m.group(1), EVENT_KEY_SOURCE_FILENAME

    if use_exif_timestamps and path.suffix.lower() in ALL_EXTS:
        ts = None
        source = EVENT_KEY_SOURCE_MTIME
        if path.suffix.lower() in IMAGE_EXTS:
            ts = read_exif_datetime(path)
            if ts is not None:
                source = EVENT_KEY_SOURCE_EXIF

        # If EXIF is missing/unreadable (or for videos), fall back to file modified time.
        if ts is None:
            try:
                ts = datetime.fromtimestamp(path.stat().st_mtime)
            except Exception:
                ts = None

        if ts:
            return ts.strftime("%Y%m%d_%H%M%S"), source

    return None, None


def event_key_for_file(path: Path, use_exif_timestamps: bool = False) -> Optional[str]:
    """Resolve a file to an event key (YYYYMMDD_HHMMSS)."""
    event_key, _ = event_key_and_source_for_file(path, use_exif_timestamps=use_exif_timestamps)
    return event_key


def group_events(
    folder: Path,
    recursive: bool = True,
    use_exif_timestamps: bool = False,
    event_source_map: Optional[dict[str, set[str]]] = None,
) -> dict[str, list[Path]]:
    """Group files by their base timestamp (the 'event key').

    Returns {event_key: [file1, file2, ...]} where event_key = "20240615_083012".
    If use_exif_timestamps=True, non-matching files use EXIF capture time when
    available (images), otherwise file modified time.
    """
    events: dict[str, list[Path]] = defaultdict(list)
    scan = folder.rglob("*") if recursive else folder.glob("*")
    for f in sorted(scan):
        if not f.is_file():
            continue
        event_key, source = event_key_and_source_for_file(f, use_exif_timestamps=use_exif_timestamps)
        if event_key:
            events[event_key].append(f)
            if event_source_map is not None and source:
                event_source_map.setdefault(event_key, set()).add(source)
    return dict(events)


def merge_events_within_window(
    events: dict[str, list[Path]],
    event_source_map: Optional[dict[str, set[str]]] = None,
    event_window_seconds: int = 0,
) -> tuple[dict[str, list[Path]], Optional[dict[str, set[str]]]]:
    """Merge adjacent events when timestamp gaps are within a configured window.

    The merged event key remains the earliest key in the cluster.
    """
    if event_window_seconds <= 0 or len(events) <= 1:
        return events, event_source_map

    keyed: list[tuple[str, datetime]] = []
    passthrough: dict[str, list[Path]] = {}
    for key, files in events.items():
        ts = parse_event_key_timestamp(key)
        if ts is None:
            passthrough[key] = files
        else:
            keyed.append((key, ts))

    if not keyed:
        return events, event_source_map

    keyed.sort(key=lambda item: item[1])
    merged_events: dict[str, list[Path]] = {}
    merged_sources: Optional[dict[str, set[str]]] = {} if event_source_map is not None else None

    current_key, last_ts = keyed[0]
    current_files = list(events[current_key])
    current_sources = set(event_source_map.get(current_key, set())) if event_source_map is not None else set()

    for key, ts in keyed[1:]:
        gap = (ts - last_ts).total_seconds()
        if gap <= event_window_seconds:
            current_files.extend(events[key])
            if event_source_map is not None:
                current_sources.update(event_source_map.get(key, set()))
            last_ts = ts
            continue

        merged_events[current_key] = current_files
        if merged_sources is not None:
            merged_sources[current_key] = set(current_sources)

        current_key, last_ts = key, ts
        current_files = list(events[key])
        current_sources = set(event_source_map.get(key, set())) if event_source_map is not None else set()

    merged_events[current_key] = current_files
    if merged_sources is not None:
        merged_sources[current_key] = set(current_sources)

    for key, files in passthrough.items():
        merged_events[key] = files
        if merged_sources is not None and event_source_map is not None:
            merged_sources[key] = set(event_source_map.get(key, set()))

    return merged_events, merged_sources


def pick_representative(files: list[Path], use_sharpness: bool = False) -> Optional[Path]:
    """Choose the single image to classify for this event group.

    With use_sharpness=False (default): base image (no variant suffix) > lowest variant number.
    With use_sharpness=True: returns the image with the highest Laplacian variance score.
    Returns None for video-only groups.
    """
    images = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
    if not images:
        return None

    if use_sharpness and len(images) > 1 and is_cv2_available():
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


def is_cv2_available() -> bool:
    """Return True when OpenCV is importable in this environment."""
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


def check_dest_not_in_source(source: Path, dest_root: Path) -> None:
    """Raise ValueError if ``dest_root`` is the same as or nested inside ``source``.

    Writing the sorted output into the folder being scanned risks copying files
    into themselves and re-scanning freshly copied files on recursive runs.
    Both paths should already be resolved by the caller.
    """
    if dest_root == source or dest_root.is_relative_to(source):
        raise ValueError(
            f"Output folder ({dest_root}) is inside the source folder ({source}). "
            "Choose an output location outside the source folder."
        )


def check_dest_not_a_file(dest_root: Path) -> None:
    """Raise ValueError if ``dest_root`` already exists as a file (not a directory).

    The output root must be a directory; pointing it at an existing file would
    fail later when creating species subfolders. The path should already be
    resolved by the caller.
    """
    if dest_root.exists() and not dest_root.is_dir():
        raise ValueError(
            f"Output folder ({dest_root}) is an existing file, not a directory. "
            "Choose a different output location."
        )


def format_run_summary(result: "RunResult") -> dict:
    """Convert a RunResult into a render-ready structure for the GUI summary card.

    Keeps the card a dumb renderer. Tolerates the empty / video-only early-return
    RunResults whose phase_timings lack 'inference'/'total_pipeline'.
    """
    rows = sorted(result.species_counts.items(), key=lambda kv: -kv[1])
    total_time = result.phase_timings.get("total_pipeline", 0.0)
    inference_time = result.phase_timings.get("inference", 0.0)
    timing = f"time: {round(total_time)}s (inference {round(inference_time)}s)"

    reports: list[str] = []
    if result.report_path:
        reports.append(Path(result.report_path).name)
    if result.csv_report_path:
        reports.append(Path(result.csv_report_path).name)

    banner = ("dry_run", "DRY RUN — no files were moved.") if result.dry_run else None

    return {
        "rows": rows,
        "total": result.total_files_sorted,
        "timing": timing,
        "reports": reports,
        "banner": banner,
        "output": str(result.output),
    }


def open_in_file_manager(path: Path) -> None:
    """Open a folder in the OS file manager.

    Raises ValueError if `path` is not an existing directory (the tested
    contract). A missing launcher or non-zero exit is logged and ignored so it
    never crashes the GUI.
    """
    if not path.is_dir():
        raise ValueError(f"Not a directory: {path}")
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows only
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except (OSError, ValueError) as e:
        logging.getLogger("trailcam_sorter").warning(
            "Could not open folder %s: %s", path, e
        )


def parse_event_key_timestamp(event_key: str) -> Optional[datetime]:
    """Parse event key like 20240615_083012 into a datetime."""
    try:
        return datetime.strptime(event_key, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def resolve_confidence_threshold(
    confidence: Optional[float],
    profile: str = "balanced",
) -> float:
    """Resolve confidence threshold from explicit value or named profile."""
    if confidence is not None:
        return confidence
    return CONFIDENCE_PROFILES.get(profile, CONFIDENCE_PROFILES["balanced"])


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
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> dict[str, dict]:
    """Run SpeciesNet on representative images in cancellable batches.

    Processes image_paths in chunks of INFERENCE_BATCH_SIZE. Between chunks it
    honours cancel_event (raising Cancelled) and reports the fraction of images
    classified so far via progress_callback. Returns {filepath_str: prediction}.
    """
    total = len(image_paths)
    log.info("Running SpeciesNet on %d images...", total)
    t0 = time.time()

    lookup: dict[str, dict] = {}
    done = 0
    for start in range(0, total, INFERENCE_BATCH_SIZE):
        if cancel_event and cancel_event.is_set():
            raise Cancelled()
        chunk = image_paths[start:start + INFERENCE_BATCH_SIZE]
        instances = [{"filepath": str(p)} for p in chunk]
        kwargs: dict = {"instances_dict": {"instances": instances}}
        if country:
            kwargs["country"] = country
        if region:
            kwargs["admin1_region"] = region
        results = model.predict(**kwargs)
        for pred in results.get("predictions", []):
            lookup[pred["filepath"]] = pred
        done += len(chunk)
        if progress_callback:
            progress_callback(done / total if total else 1.0)

    elapsed = time.time() - t0
    log.info("Inference done in %.1f s  (%.2f s/image)",
             elapsed, elapsed / max(total, 1))
    return lookup


def load_classifier_backend(backend: str, log: logging.Logger):
    """Load the configured classifier backend."""
    if backend == "speciesnet":
        return load_model(log)
    raise ValueError(f"Unsupported classifier backend: {backend}")


def classify_with_backend(
    backend: str,
    model,
    image_paths: list[Path],
    country: Optional[str],
    region: Optional[str],
    log: logging.Logger,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> dict[str, dict]:
    """Dispatch classification to the configured backend implementation."""
    if backend == "speciesnet":
        return classify_images(
            model, image_paths, country, region, log,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
        )
    raise ValueError(f"Unsupported classifier backend: {backend}")


# ---------------------------------------------------------------------------
# File mover / copier
# ---------------------------------------------------------------------------

class Cancelled(Exception):
    pass


@dataclass
class RunResult:
    source: Path
    output: Path
    dry_run: bool
    total_files_scanned: int
    total_events: int
    classified_image_events: int
    video_only_events: int
    total_files_sorted: int
    species_counts: dict[str, int]
    review_files: int
    phase_timings: dict[str, float]
    video_matching: dict[str, int]
    event_key_sources: dict[str, int]
    exact_duplicates_skipped: int = 0
    report_path: Optional[Path] = None
    csv_report_path: Optional[Path] = None
    checkpoint_path: Optional[Path] = None


def build_video_match_candidates(
    rep_map: dict[str, Path],
    predictions: dict[str, dict],
    min_confidence: float,
) -> tuple[dict[str, str], list[tuple[datetime, str, float]]]:
    """Build matching candidates from confidently classified image events.

    Returns (minute_species, nearest_candidates):
    - minute_species: {minute_prefix: species} for legacy minute-bucket matching
    - nearest_candidates: [(timestamp, species, score), ...] for nearest matching
    """
    minute_species: dict[str, str] = {}
    candidates: list[tuple[datetime, str, float]] = []
    for ek, rep in rep_map.items():
        pred = predictions.get(str(rep), {})
        lbl = pred.get("prediction", "")
        sc = pred.get("prediction_score", 0.0) or 0.0
        sp = sanitize_label(lbl) if lbl else ""
        ts = parse_event_key_timestamp(ek)
        if ts and sp and sp.lower() != "blank" and sc >= min_confidence and "unknown" not in lbl.lower():
            minute_species[ek[:13]] = sp
            candidates.append((ts, sp, float(sc)))
    return minute_species, candidates


def match_video_event(
    event_key: str,
    mode: str,
    minute_species: dict[str, str],
    candidates: list[tuple[datetime, str, float]],
) -> tuple[Optional[str], Optional[float]]:
    """Match a video-only event to a species using the selected strategy.

    Returns (species, gap_seconds). gap_seconds is only set for nearest matches.
    """
    if mode == "minute":
        return minute_species.get(event_key[:13]), None

    event_ts = parse_event_key_timestamp(event_key)
    if event_ts and candidates:
        ranked = sorted(
            candidates,
            key=lambda c: (abs((c[0] - event_ts).total_seconds()), -c[2]),
        )
        best_ts, best_species, _ = ranked[0]
        gap_s = abs((best_ts - event_ts).total_seconds())
        if gap_s <= VIDEO_MATCH_MAX_GAP_SECONDS:
            return best_species, gap_s
    return None, None


def compute_file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """Compute SHA256 for exact duplicate detection; returns None on read failure."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


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
    dedupe_exact: bool = False,
    video_match_mode: Literal["nearest", "minute"] = "nearest",
    progress_callback: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    video_match_stats: Optional[dict[str, int]] = None,
    dedupe_stats: Optional[dict[str, int]] = None,
) -> dict[str, int]:
    """Copy/move files into species subfolders, renamed to yyyy-mm-dd_HH-MM-SS_species.ext.

    Blank predictions are skipped. Low-confidence/unknown go to Review/.
    Video-only events are matched by the selected strategy:
    - nearest: nearest confidently classified image event within VIDEO_MATCH_MAX_GAP_SECONDS
    - minute: legacy minute-bucket matching
    Returns counter {species_folder: count}.
    """
    stats: dict[str, int] = defaultdict(int)
    local_video_match_stats: dict[str, int] = {
        "video_only_events": 0,
        "video_matched_nearest": 0,
        "video_matched_minute": 0,
        "video_unmatched": 0,
    }
    action = shutil.move if move else shutil.copy2
    verb = "MOVE" if move else "COPY"
    reserved_destinations: set[str] = set()
    seen_hashes: set[str] = set()
    duplicates_skipped = 0

    # Build candidates for video-only matching from confidently classified image events.
    minute_species, video_match_candidates = build_video_match_candidates(
        rep_map, predictions, min_confidence,
    )

    total_events = len(events)
    for i, (event_key, files) in enumerate(events.items()):
        if cancel_event and cancel_event.is_set():
            raise Cancelled()
        if progress_callback:
            progress_callback(0.85 + 0.15 * (i / max(total_events, 1)))

        rep = rep_map.get(event_key)
        if rep is None:
            local_video_match_stats["video_only_events"] += 1
            species_name, gap_s = match_video_event(
                event_key, video_match_mode, minute_species, video_match_candidates,
            )
            if species_name:
                if video_match_mode == "minute":
                    local_video_match_stats["video_matched_minute"] += 1
                    log.debug(
                        "Event %s: video matched to '%s' by legacy minute bucket",
                        event_key,
                        species_name,
                    )
                else:
                    local_video_match_stats["video_matched_nearest"] += 1
                    log.debug(
                        "Event %s: video matched to '%s' by nearest image event (%.0f sec gap)",
                        event_key,
                        species_name,
                        gap_s,
                    )

            if not species_name:
                local_video_match_stats["video_unmatched"] += 1
                if video_match_mode == "minute":
                    log.debug("Event %s: video-only, no image match within same minute, skipping", event_key)
                else:
                    log.debug(
                        "Event %s: video-only, no image match within %d seconds, skipping",
                        event_key,
                        VIDEO_MATCH_MAX_GAP_SECONDS,
                    )
                continue
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
            if dedupe_exact:
                digest = compute_file_sha256(f)
                if digest:
                    if digest in seen_hashes:
                        duplicates_skipped += 1
                        log.debug("Skipping exact duplicate: %s", f.name)
                        continue
                    seen_hashes.add(digest)

            ext = f.suffix.lower()
            stem = f"{date_str}_{time_str}_{species_name}"
            dst = target_dir / f"{stem}{ext}"
            i2 = 2
            while dst.exists() or str(dst) in reserved_destinations:
                dst = target_dir / f"{stem}_{i2}{ext}"
                i2 += 1
            reserved_destinations.add(str(dst))

            if dry_run:
                log.debug("[DRY RUN] %s  %s  ->  %s/%s", verb, f.name, species_name, dst.name)
            else:
                target_dir.mkdir(parents=True, exist_ok=True)
                action(str(f), str(dst))
                log.debug("%s  %s  ->  %s/%s", verb, f.name, species_name, dst.name)

            stats[species_name] += 1

    if video_match_stats is not None:
        video_match_stats.clear()
        video_match_stats.update(local_video_match_stats)
    if dedupe_stats is not None:
        dedupe_stats.clear()
        dedupe_stats.update({"exact_duplicates_skipped": duplicates_skipped})

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
    phase_timings: Optional[dict[str, float]] = None,
    video_match_stats: Optional[dict[str, int]] = None,
    grouping_source_stats: Optional[dict[str, int]] = None,
    dedupe_stats: Optional[dict[str, int]] = None,
):
    video_only_events = (
        video_match_stats.get("video_only_events", 0)
        if video_match_stats
        else max(len(events) - len(rep_map), 0)
    )
    exif_events = grouping_source_stats.get("exif_derived_events", 0) if grouping_source_stats else 0
    mtime_events = grouping_source_stats.get("mtime_derived_events", 0) if grouping_source_stats else 0

    report = {
        "generated": datetime.now().isoformat(),
        "total_events": len(events),
        "total_files_sorted": sum(stats.values()),
        "summary": {
            "classified_image_events": len(rep_map),
            "video_only_events": video_only_events,
            "exif_derived_events": exif_events,
            "mtime_derived_events": mtime_events,
            "exact_duplicates_skipped": dedupe_stats.get("exact_duplicates_skipped", 0) if dedupe_stats else 0,
        },
        "timings_seconds": phase_timings or {},
        "video_matching": video_match_stats or {
            "video_only_events": video_only_events,
            "video_matched_nearest": 0,
            "video_matched_minute": 0,
            "video_unmatched": 0,
        },
        "event_key_sources": grouping_source_stats or {
            "filename_events": len(events),
            "exif_derived_events": 0,
            "mtime_derived_events": 0,
        },
        "duplicate_handling": dedupe_stats or {"exact_duplicates_skipped": 0},
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
    return report_path


def write_species_csv(
    dest_root: Path,
    stats: dict[str, int],
    log: logging.Logger,
    csv_path: Optional[Path] = None,
) -> Path:
    """Write species/category counts to CSV for spreadsheet analysis."""
    output_path = csv_path if csv_path is not None else (dest_root / "_sort_report.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = sum(stats.values())
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "count", "percent_of_sorted"])
        for category, count in sorted(stats.items(), key=lambda x: -x[1]):
            pct = (count / total * 100.0) if total else 0.0
            writer.writerow([category, count, f"{pct:.2f}"])

    log.info("CSV report saved to %s", output_path)
    return output_path


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
    classifier_backend: str = "speciesnet",
    dedupe_exact: bool = False,
    video_match_mode: Literal["nearest", "minute"] = "nearest",
    use_exif_timestamps: bool = True,
    recursive: bool = True,
    event_window_seconds: int = 0,
    report_csv: Optional[Path] = None,
    checkpoint_path: Optional[Path] = None,
    resume_from_checkpoint: bool = False,
    progress_callback: Optional[Callable[[float], None]] = None,
    status_callback: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
)-> RunResult:
    """Run the full sort pipeline. Raises Cancelled if cancel_event is set."""
    def check():
        if cancel_event and cancel_event.is_set():
            raise Cancelled()

    def status(msg: str):
        if status_callback:
            status_callback(msg)

    if progress_callback:
        progress_callback(0.0)

    run_start = time.perf_counter()
    phase_timings: dict[str, float] = {}

    log.info("Source : %s", source)
    log.info("Output : %s", dest_root)
    log.info("Mode   : %s", "MOVE" if move else "COPY")
    log.info("Classifier backend: %s", classifier_backend)
    log.info("Exact dedupe: %s", "enabled" if dedupe_exact else "disabled")
    log.info("Video match mode: %s", video_match_mode)
    if use_exif_timestamps:
        log.info("EXIF fallback: enabled (for images without timestamp-style filenames)")
    else:
        log.warning(
            "EXIF fallback: disabled (strict timestamp-style filenames only). "
            "Non-matching files may be skipped."
        )
    if dry_run:
        log.info("*** DRY RUN -- no files will be touched ***")
    if checkpoint_path:
        log.info("Checkpoint file: %s", checkpoint_path)
        if resume_from_checkpoint:
            log.info("Resume mode: enabled")

    # 1. Group files by event
    check()
    status("Scanning files…")
    group_start = time.perf_counter()
    event_source_map: dict[str, set[str]] = {}
    events = group_events(
        source,
        recursive=recursive,
        use_exif_timestamps=use_exif_timestamps,
        event_source_map=event_source_map,
    )
    events, merged_sources = merge_events_within_window(
        events,
        event_source_map=event_source_map,
        event_window_seconds=event_window_seconds,
    )
    if merged_sources is not None:
        event_source_map = merged_sources

    completed_before: set[str] = set()
    if checkpoint_path and resume_from_checkpoint:
        completed_before = load_checkpoint(checkpoint_path)
        if completed_before:
            events = {k: v for k, v in events.items() if k not in completed_before}
            event_source_map = {k: v for k, v in event_source_map.items() if k in events}
            log.info("Resume filter: skipped %d previously completed events", len(completed_before))

    phase_timings["group_events"] = time.perf_counter() - group_start
    total_files = sum(len(v) for v in events.values())
    if not events:
        log.warning("No matching files found in %s", source)
        return RunResult(
            source=source,
            output=dest_root,
            dry_run=dry_run,
            total_files_scanned=0,
            total_events=0,
            classified_image_events=0,
            video_only_events=0,
            total_files_sorted=0,
            species_counts={},
            review_files=0,
            phase_timings=phase_timings,
            video_matching={
                "video_only_events": 0,
                "video_matched_nearest": 0,
                "video_matched_minute": 0,
                "video_unmatched": 0,
            },
            event_key_sources={
                "filename_events": 0,
                "exif_derived_events": 0,
                "mtime_derived_events": 0,
            },
            checkpoint_path=checkpoint_path,
        )

    filename_events = sum(
        1 for srcs in event_source_map.values() if EVENT_KEY_SOURCE_FILENAME in srcs
    )
    exif_derived_events = sum(
        1
        for srcs in event_source_map.values()
        if EVENT_KEY_SOURCE_FILENAME not in srcs and EVENT_KEY_SOURCE_EXIF in srcs
    )
    mtime_derived_events = sum(
        1
        for srcs in event_source_map.values()
        if EVENT_KEY_SOURCE_FILENAME not in srcs and EVENT_KEY_SOURCE_EXIF not in srcs and EVENT_KEY_SOURCE_MTIME in srcs
    )
    grouping_source_stats = {
        "filename_events": filename_events,
        "exif_derived_events": exif_derived_events,
        "mtime_derived_events": mtime_derived_events,
    }

    log.info("Found %d events encompassing %d files", len(events), total_files)
    if event_window_seconds > 0:
        log.info("Event merge window: %d second(s)", event_window_seconds)
    if exif_derived_events or mtime_derived_events:
        log.info(
            "Event key sources: filename=%d, exif-derived=%d, mtime-derived=%d",
            filename_events,
            exif_derived_events,
            mtime_derived_events,
        )
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
        return RunResult(
            source=source,
            output=dest_root,
            dry_run=dry_run,
            total_files_scanned=total_files,
            total_events=len(events),
            classified_image_events=0,
            video_only_events=len(events),
            total_files_sorted=0,
            species_counts={},
            review_files=0,
            phase_timings=phase_timings,
            video_matching={
                "video_only_events": len(events),
                "video_matched_nearest": 0,
                "video_matched_minute": 0,
                "video_unmatched": len(events),
            },
            event_key_sources=grouping_source_stats,
        )

    if sharpness and not is_cv2_available():
        log.warning("--sharpest enabled but OpenCV (cv2) is not available; "
                    "falling back to default representative selection.")

    if progress_callback:
        progress_callback(0.10)

    # 3. Load model & run inference (cannot be interrupted mid-inference)
    status("Loading model…")
    load_start = time.perf_counter()
    model = load_classifier_backend(classifier_backend, log)
    phase_timings["load_model"] = time.perf_counter() - load_start
    if progress_callback:
        progress_callback(0.20)

    status(f"Running inference on {len(images_to_classify)} images…")
    inference_start = time.perf_counter()
    _outer_progress = progress_callback

    def _inference_progress(frac: float):
        if _outer_progress:
            _outer_progress(0.20 + 0.65 * frac)

    predictions = classify_with_backend(
        classifier_backend,
        model,
        images_to_classify,
        country,
        region,
        log,
        cancel_event=cancel_event,
        progress_callback=_inference_progress,
    )
    phase_timings["inference"] = time.perf_counter() - inference_start
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
    sort_start = time.perf_counter()
    video_match_stats: dict[str, int] = {}
    dedupe_stats: dict[str, int] = {}
    stats = sort_files(
        events, predictions, rep_map,
        dest_root, confidence, move, dry_run, log,
        subfolders=subfolders,
        sharpness=sharpness,
        dedupe_exact=dedupe_exact,
        video_match_mode=video_match_mode,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        video_match_stats=video_match_stats,
        dedupe_stats=dedupe_stats,
    )
    phase_timings["sort_files"] = time.perf_counter() - sort_start
    phase_timings["total_pipeline"] = time.perf_counter() - run_start
    log.info(
        "Video matching: video-only=%d, matched-nearest=%d, matched-minute=%d, unmatched=%d",
        video_match_stats.get("video_only_events", 0),
        video_match_stats.get("video_matched_nearest", 0),
        video_match_stats.get("video_matched_minute", 0),
        video_match_stats.get("video_unmatched", 0),
    )

    report_path: Optional[Path] = None
    csv_report_path: Optional[Path] = None

    # 5. Write report
    if not dry_run:
        report_path = write_report(
            dest_root,
            events,
            predictions,
            rep_map,
            stats,
            log,
            phase_timings=phase_timings,
            video_match_stats=video_match_stats,
            grouping_source_stats=grouping_source_stats,
            dedupe_stats=dedupe_stats,
        )
        if report_csv is not None:
            csv_report_path = write_species_csv(
                dest_root=dest_root,
                stats=stats,
                log=log,
                csv_path=report_csv,
            )
        if checkpoint_path:
            completed_now = set(events.keys())
            save_checkpoint(checkpoint_path, completed_before.union(completed_now))
            log.info("Checkpoint updated with %d completed events", len(completed_before.union(completed_now)))
    elif checkpoint_path:
        log.info("Checkpoint not updated during dry run")

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
    log.info(
        "RUN SUMMARY | files=%d events=%d reps=%d video_only=%d sorted=%d review=%d exif_events=%d mtime_events=%d unmatched_video_only=%d",
        total_files,
        len(events),
        len(rep_map),
        max(len(events) - len(rep_map), 0),
        total_sorted,
        stats.get("Review", 0),
        grouping_source_stats.get("exif_derived_events", 0),
        grouping_source_stats.get("mtime_derived_events", 0),
        video_match_stats.get("video_unmatched", 0),
    )
    log.info("Duplicates skipped (exact hash): %d", dedupe_stats.get("exact_duplicates_skipped", 0))
    log.info(
        "TIMINGS (s) | group=%.2f load=%.2f inference=%.2f sort=%.2f total=%.2f",
        phase_timings.get("group_events", 0.0),
        phase_timings.get("load_model", 0.0),
        phase_timings.get("inference", 0.0),
        phase_timings.get("sort_files", 0.0),
        phase_timings.get("total_pipeline", 0.0),
    )
    log.info("Output: %s", dest_root)

    status(f"Complete — {total_sorted} file{'s' if total_sorted != 1 else ''} sorted")
    if progress_callback:
        progress_callback(1.0)

    return RunResult(
        source=source,
        output=dest_root,
        dry_run=dry_run,
        total_files_scanned=total_files,
        total_events=len(events),
        classified_image_events=len(rep_map),
        video_only_events=max(len(events) - len(rep_map), 0),
        total_files_sorted=total_sorted,
        species_counts=dict(sorted(stats.items(), key=lambda x: -x[1])),
        review_files=stats.get("Review", 0),
        phase_timings=phase_timings,
        video_matching=video_match_stats,
        event_key_sources=grouping_source_stats,
        exact_duplicates_skipped=dedupe_stats.get("exact_duplicates_skipped", 0),
        report_path=report_path,
        csv_report_path=csv_report_path,
        checkpoint_path=checkpoint_path,
    )


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
        self.root.title(f"TrailCam Sorter v{__version__}")
        self.root.geometry("820x720")
        self.root.resizable(True, True)
        self.root.minsize(680, 500)
        self.root.configure(fg_color="#161c24")

        self._q: queue.Queue = queue.Queue()
        self._running = False
        self._busy = False
        self._anim_tick = 0.0
        self._cancel_event = threading.Event()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    def _build_ui(self):
        ctk = self.ctk
        self._settings = resolve_startup_settings(load_config())

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
        # Defaults reused outside _build_ui (e.g. resetting after a pending cancel).
        self._progress_color = GREEN
        self._status_color = DIM
        self._err_color = ERROR_RED
        self._pending_result = None
        self._pending_error = None

        def section_header(text: str, parent=None):
            row = ctk.CTkFrame(parent if parent is not None else self.root, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(10, 0))
            ctk.CTkLabel(
                row, text=text,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                text_color=MUTED,
            ).pack(side="left")
            ctk.CTkFrame(row, height=1, fg_color=SEP).pack(
                side="left", fill="x", expand=True, padx=(8, 0)
            )
            return row

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

        # ── Tabbed body + persistent run bar ─────────────────────────────
        # The run bar is packed first against the bottom so it stays pinned;
        # the tabview then fills the remaining space above it.
        run_bar = ctk.CTkFrame(self.root, fg_color=BG)
        run_bar.pack(side="bottom", fill="x")

        self.tabs = ctk.CTkTabview(
            self.root, fg_color=BG,
            segmented_button_fg_color=CARD,
            segmented_button_selected_color=GREEN,
            segmented_button_selected_hover_color=GREEN_H,
            segmented_button_unselected_color=CARD,
            segmented_button_unselected_hover_color=CLOSE_H,
            text_color=TEXT,
        )
        self.tabs.pack(side="top", fill="both", expand=True, padx=8, pady=(6, 0))
        self.tabs.add("Setup")
        self.tabs.add("Run & Log")
        # Setup content scrolls so advanced mode can never overflow its tab.
        setup_tab = ctk.CTkScrollableFrame(self.tabs.tab("Setup"), fg_color="transparent")
        setup_tab.pack(fill="both", expand=True)
        runlog_tab = self.tabs.tab("Run & Log")

        # ── Folders ──────────────────────────────────────────────────────
        section_header("INPUT / OUTPUT", setup_tab)
        folders = ctk.CTkFrame(setup_tab, fg_color=CARD, corner_radius=8)
        folders.pack(fill="x", padx=16, pady=(6, 0))
        folders.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            folders, text="Source",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=DIM, width=64, anchor="w",
        ).grid(row=0, column=0, padx=(16, 6), pady=(16, 6), sticky="w")
        self.src_var = ctk.StringVar(value=display_path(self._settings["last_source"]))
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
        self.out_var = ctk.StringVar(value=display_path(self._settings["last_output"]))
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
        section_header("OPTIONS", setup_tab)
        opts = ctk.CTkFrame(setup_tab, fg_color=CARD, corner_radius=8)
        opts.pack(fill="x", padx=16, pady=(6, 0))

        mode_row = ctk.CTkFrame(opts, fg_color="transparent")
        mode_row.pack(fill="x", padx=16, pady=(12, 4))

        self.advanced_mode_var = ctk.BooleanVar(value=self._settings["advanced_mode"])
        ctk.CTkCheckBox(
            mode_row,
            text="Advanced mode",
            variable=self.advanced_mode_var,
            fg_color=GREEN,
            hover_color=GREEN_H,
            checkmark_color="white",
            command=self._on_advanced_mode_toggle,
        ).pack(side="left")

        self.mode_hint_label = ctk.CTkLabel(
            mode_row,
            text="Basic mode shows common options. Enable advanced mode for expert controls.",
            font=ctk.CTkFont(size=10),
            text_color=MUTED,
            anchor="w",
        )
        self.mode_hint_label.pack(side="left", padx=(12, 0))

        basic_row = ctk.CTkFrame(opts, fg_color="transparent")
        basic_row.pack(fill="x", padx=16, pady=(6, 8))

        self.recursive_var = ctk.BooleanVar(value=self._settings["recursive"])
        ctk.CTkCheckBox(
            basic_row, text="Scan subfolders", variable=self.recursive_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(0, 22))

        self.move_var = ctk.BooleanVar(value=self._settings["move"])
        ctk.CTkCheckBox(
            basic_row, text="Move files", variable=self.move_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(0, 22))

        self.dry_var = ctk.BooleanVar(value=self._settings["dry_run"])
        ctk.CTkCheckBox(
            basic_row, text="Dry run", variable=self.dry_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(0, 22))

        basic_geo_row = ctk.CTkFrame(opts, fg_color="transparent")
        basic_geo_row.pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkLabel(
            basic_geo_row,
            text="Country",
            font=ctk.CTkFont(size=11),
            text_color=DIM,
        ).pack(side="left", padx=(0, 6))
        self.country_var = ctk.StringVar(value=self._settings["country"])
        self.country_combo = ctk.CTkComboBox(
            basic_geo_row,
            variable=self.country_var,
            width=96,
            values=COUNTRY_CODES,
            fg_color=INNER,
            border_color=SEP,
            button_color=SEP,
            button_hover_color=CLOSE_H,
            dropdown_fg_color=INNER,
            dropdown_hover_color=CLOSE_H,
            dropdown_text_color=TEXT,
            command=self._on_country_change,
        )
        self.country_combo.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(
            basic_geo_row,
            text="Region (US)",
            font=ctk.CTkFont(size=11),
            text_color=DIM,
        ).pack(side="left", padx=(0, 6))
        self.region_var = ctk.StringVar(value=self._settings["region"])
        self.region_combo = ctk.CTkComboBox(
            basic_geo_row,
            variable=self.region_var,
            width=86,
            values=US_STATES,
            state="disabled",
            fg_color=INNER,
            border_color=SEP,
            button_color=SEP,
            button_hover_color=CLOSE_H,
            dropdown_fg_color=INNER,
            dropdown_hover_color=CLOSE_H,
            dropdown_text_color=TEXT,
        )
        self.region_combo.pack(side="left", padx=(0, 28))

        ctk.CTkLabel(
            basic_geo_row,
            text="Confidence",
            font=ctk.CTkFont(size=11),
            text_color=DIM,
        ).pack(side="left", padx=(0, 8))
        self.conf_var = ctk.DoubleVar(value=self._settings["confidence"])
        ctk.CTkSlider(
            basic_geo_row,
            from_=0.1,
            to=0.9,
            number_of_steps=16,
            variable=self.conf_var,
            width=140,
            button_color=GREEN,
            button_hover_color=GREEN_H,
            progress_color=GREEN,
            fg_color=INNER,
            command=lambda v: self.conf_label.configure(text=f"{float(v):.2f}"),
        ).pack(side="left")
        self.conf_label = ctk.CTkLabel(
            basic_geo_row,
            text=f"{self._settings['confidence']:.2f}",
            width=40,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT,
        )
        self.conf_label.pack(side="left", padx=(6, 18))

        ctk.CTkLabel(
            basic_geo_row,
            text="Geofencing optional · Region applies to USA only · lower confidence = more results",
            font=ctk.CTkFont(size=10),
            text_color=MUTED,
        ).pack(side="left")

        self.advanced_frame = ctk.CTkFrame(opts, fg_color="transparent")
        self.advanced_frame.pack(fill="x", padx=0, pady=(0, 10))

        ctk.CTkLabel(
            self.advanced_frame,
            text="Advanced options for output layout and event handling.",
            font=ctk.CTkFont(size=10), text_color=MUTED, anchor="w",
        ).pack(fill="x", padx=16, pady=(2, 8))

        ctk.CTkFrame(self.advanced_frame, height=1, fg_color=SEP).pack(fill="x", padx=12, pady=(0, 10))

        chk_row = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        chk_row.pack(fill="x", padx=16, pady=(0, 14))

        self.subfolders_var = ctk.BooleanVar(value=self._settings["species_subfolders"])
        ctk.CTkCheckBox(
            chk_row, text="Species subfolders", variable=self.subfolders_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(0, 22))

        self.sharpness_var = ctk.BooleanVar(value=self._settings["sharpness"])
        ctk.CTkCheckBox(
            chk_row, text="Pick sharpest frame", variable=self.sharpness_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left")

        self.exif_var = ctk.BooleanVar(value=self._settings["exif_fallback"])
        ctk.CTkCheckBox(
            chk_row, text="Use EXIF/modified-time fallback (recommended)", variable=self.exif_var,
            fg_color=GREEN, hover_color=GREEN_H, checkmark_color="white",
        ).pack(side="left", padx=(22, 0))

        self._set_advanced_mode(self._settings["advanced_mode"])
        # Sync region combo enabled-state to the restored country.
        self._on_country_change(self._settings["country"])

        # ── Run controls (persistent bar, visible from both tabs) ────────
        run_card = ctk.CTkFrame(run_bar, fg_color=CARD, corner_radius=8)
        run_card.pack(fill="x", padx=16, pady=(8, 10))

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
            command=self._on_close,
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

        # ── Summary card (populated on completion) ───────────────────────
        self.summary_card = ctk.CTkFrame(runlog_tab, fg_color=INNER, corner_radius=8)
        # Not packed yet; _render_summary packs it when there is something to show.

        self.summary_banner = ctk.CTkLabel(
            self.summary_card, text="", anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
        )  # packed/hidden dynamically

        self._summary_header_row = header_row = ctk.CTkFrame(self.summary_card, fg_color="transparent")
        header_row.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            header_row, text="RESULTS", anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
        ).pack(side="left")
        self.open_folder_btn = ctk.CTkButton(
            header_row, text="Open folder", height=28, width=110,
            fg_color=GREEN, hover_color=GREEN_H,
            font=ctk.CTkFont(size=12), command=self._open_folder,
        )
        self.open_folder_btn.pack(side="right")

        self.summary_body = ctk.CTkLabel(
            self.summary_card, text="", anchor="w", justify="left",
            font=ctk.CTkFont(size=12, family="Consolas"), text_color=TEXT,
        )
        self.summary_body.pack(fill="x", padx=12, pady=(0, 4))

        self.summary_meta = ctk.CTkLabel(
            self.summary_card, text="", anchor="w", justify="left",
            font=ctk.CTkFont(size=11), text_color=DIM,
        )
        self.summary_meta.pack(fill="x", padx=12, pady=(0, 10))

        # ── Activity log ─────────────────────────────────────────────────
        self._log_header_row = section_header("ACTIVITY LOG", runlog_tab)
        self.log_box = ctk.CTkTextbox(
            runlog_tab,
            height=140,
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

    def _set_advanced_mode(self, enabled: bool):
        if enabled:
            self.advanced_frame.pack(fill="x", padx=0, pady=(0, 10))
            self.mode_hint_label.configure(
                text="Advanced mode enabled: expert controls are visible."
            )
        else:
            self.advanced_frame.pack_forget()
            self.mode_hint_label.configure(
                text="Basic mode shows common options, including geofencing and confidence. Enable advanced mode for expert controls."
            )

    def _on_advanced_mode_toggle(self):
        self._set_advanced_mode(self.advanced_mode_var.get())

    def _browse(self, var, title: str):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title=title, parent=self.root)
        if folder:
            var.set(display_path(folder))

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
                elif kind == "result":
                    self._pending_result = value
                elif kind == "error":
                    self._pending_error = value
                elif kind == "done":
                    self._set_progress(1.0 if value == "ok" else self.progress.get())
                    self.run_btn.configure(state="normal", text="▶  Run Sort")
                    # Clear the transient "cancelling" affordances now that the
                    # run has actually stopped — otherwise the amber status/bar
                    # and "Cancelling…" button linger until the next run.
                    self.cancel_btn.configure(state="disabled", text="Cancel")
                    self.progress.configure(progress_color=self._progress_color)
                    if value == "cancelled":
                        self.status_label.configure(
                            text="Cancelled.", text_color=self._status_color
                        )
                    self.close_btn.configure(state="normal")
                    self._running = False
                    self._render_summary(value)
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
        if self._busy:
            # Model load / inference run as a single atomic call and cannot be
            # interrupted partway; cancel takes effect the moment it returns.
            # Recolour the bar + status amber so the pending cancel is obvious
            # even though the bar keeps animating (work IS still happening).
            self.progress.configure(progress_color=WARN_AMBER)
            self.status_label.configure(
                text="⚠ Cancelling — finishing current inference batch first…",
                text_color=WARN_AMBER,
            )
            self._append_log(
                "Cancelling — the current inference batch can't be stopped midway; "
                "it will stop as soon as that finishes (the bar keeps moving until then)."
            )
        else:
            self._append_log("Cancelling — will stop after the current operation…")

    def _render_summary(self, status: str):
        """Populate + show the summary card from stashed result/error state.

        Called once from the 'done' handler. `status` is 'ok' | 'cancelled' |
        'error'. Cancelled runs show nothing (card stays hidden).
        """
        if status == "error":
            msg = self._pending_error or "Run failed — see the activity log for details."
            self.summary_banner.configure(text=f"⚠ Error: {msg}", text_color=self._err_color)
            self.summary_banner.pack(fill="x", padx=12, pady=(10, 0), before=self._summary_header_row)
            self.summary_body.configure(text="")
            self.summary_meta.configure(text="")
            self.open_folder_btn.configure(state="disabled")
            self.summary_card.pack(fill="x", padx=16, pady=(6, 10), before=self._log_header_row)
            from tkinter import messagebox
            messagebox.showerror("Sort failed", msg, parent=self.root)
            return

        if status != "ok" or self._pending_result is None:
            return  # cancelled or nothing to show

        s = format_run_summary(self._pending_result)
        self._summary_output = s["output"]

        if s["banner"] is not None:
            _, text = s["banner"]  # dry-run banner
            self.summary_banner.configure(text=text, text_color=WARN_AMBER)
            self.summary_banner.pack(fill="x", padx=12, pady=(10, 0), before=self._summary_header_row)
        else:
            self.summary_banner.pack_forget()

        width = 30
        lines = [f"{label:.<{width}} {count}" for label, count in s["rows"]]
        lines.append(f"{'-' * width}")
        lines.append(f"{'TOTAL':.<{width}} {s['total']}")
        self.summary_body.configure(text="\n".join(lines))

        meta_parts = [s["timing"]]
        if s["reports"]:
            meta_parts.append("report: " + " · ".join(s["reports"]))
        self.summary_meta.configure(text="\n".join(meta_parts))

        # A dry run writes nothing, so there is no output to open.
        self.open_folder_btn.configure(state="disabled" if s["banner"] is not None else "normal")
        self.summary_card.pack(fill="x", padx=16, pady=(6, 10), before=self._log_header_row)

    def _open_folder(self):
        path = getattr(self, "_summary_output", None)
        if not path:
            return
        try:
            open_in_file_manager(Path(path))
        except ValueError as e:
            self._append_log(str(e))

    def _collect_settings(self) -> dict:
        """Read current GUI fields into a config dict for persistence.

        Excludes the move/dry_run action toggles, which always start in the
        safe state on the next launch.
        """
        return {
            "last_source": self.src_var.get().strip(),
            "last_output": self.out_var.get().strip(),
            "advanced_mode": self.advanced_mode_var.get(),
            "recursive": self.recursive_var.get(),
            "country": self.country_var.get().strip(),
            "region": self.region_var.get().strip(),
            "confidence": self.conf_var.get(),
            "species_subfolders": self.subfolders_var.get(),
            "sharpness": self.sharpness_var.get(),
            "exif_fallback": self.exif_var.get(),
        }

    def _on_close(self):
        """Window-close handler: confirm and cancel a running sort before quitting."""
        if self._running:
            from tkinter import messagebox
            if not messagebox.askyesno(
                "Quit while running?",
                "A sort is still running. Cancel it and quit?",
                parent=self.root,
            ):
                return
            self._cancel_event.set()
        save_config(self._collect_settings())
        self.root.destroy()

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

        dest_root = Path(self.out_var.get().strip()).resolve()
        try:
            check_dest_not_a_file(dest_root)
            check_dest_not_in_source(source.resolve(), dest_root)
        except ValueError as e:
            from tkinter import messagebox
            messagebox.showerror("Invalid output folder", str(e), parent=self.root)
            self._append_log(str(e))
            return

        save_config(self._collect_settings())

        self.log_box.delete("1.0", "end")
        self._set_progress(0)
        self.progress.configure(progress_color=self._progress_color)
        self.pct_label.configure(text="")
        self.status_label.configure(text="", text_color=self._status_color)
        self.summary_card.pack_forget()
        self._pending_result = None
        self._pending_error = None
        self._summary_output = None
        self._cancel_event.clear()
        self.run_btn.configure(state="disabled", text="Running…")
        self.cancel_btn.configure(state="normal", text="Cancel")
        self.close_btn.configure(state="disabled")
        self.tabs.set("Run & Log")  # surface the streaming log + results
        self._running = True
        self.root.after(100, self._poll)

        log = logging.getLogger("trailcam_gui")
        log.setLevel(logging.DEBUG)
        log.handlers.clear()
        handler = _QueueHandler(self._q)
        handler.setFormatter(logging.Formatter(LOG_FMT_SHORT))
        log.addHandler(handler)

        country = self.country_var.get().strip() or None
        region = self.region_var.get().strip() or None

        def worker():
            try:
                result = run_sort(
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
                    classifier_backend="speciesnet",
                    dedupe_exact=False,
                    recursive=self.recursive_var.get(),
                    use_exif_timestamps=self.exif_var.get(),
                    event_window_seconds=0,
                    report_csv=None,
                    progress_callback=lambda v: self._q.put(("progress", v)),
                    status_callback=lambda s: self._q.put(("status", s)),
                    cancel_event=self._cancel_event,
                )
                self._q.put(("result", result))
                self._q.put(("done", "ok"))
            except Cancelled:
                self._q.put(("log", "Run cancelled."))
                self._q.put(("done", "cancelled"))
            except Exception as e:
                log.exception("Unexpected error")
                self._q.put(("error", str(e)))
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
    parser.add_argument("-c", "--confidence", type=float, default=None,
                        help="Minimum confidence threshold (0-1). Overrides --confidence-profile.")
    parser.add_argument(
        "--confidence-profile",
        choices=tuple(CONFIDENCE_PROFILES.keys()),
        default="balanced",
        help="Confidence preset: conservative=0.60, balanced=0.40 (default), recall=0.25",
    )
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
    parser.add_argument("--video-match-mode", choices=VIDEO_MATCH_MODES, default="nearest",
                        help="Video-only matching strategy: nearest (default) or minute (legacy behavior).")
    parser.add_argument("--classifier-backend", choices=CLASSIFIER_BACKENDS, default="speciesnet",
                        help="Classifier backend implementation (default: speciesnet).")
    parser.add_argument("--use-exif-timestamps", action="store_true", dest="use_exif_timestamps",
                        help="Use EXIF/modified-time fallback for non-standard filenames (recommended, default: on).")
    parser.add_argument("--no-exif-timestamps", action="store_false", dest="use_exif_timestamps",
                        help="Advanced: disable fallback and require strict timestamp-style filenames only.")
    parser.add_argument("--report-csv", default=None,
                        help="Optional path to write species/category counts CSV.")
    parser.add_argument("--dedupe-exact", action="store_true",
                        help="Skip exact duplicate files based on content hash.")
    parser.add_argument("--event-window-seconds", type=int, default=0,
                        help="Merge adjacent timestamp events within this gap in seconds (default: 0, disabled).")
    parser.add_argument("--checkpoint-file", default=None,
                        help="Optional checkpoint JSON path for completed event keys.")
    parser.add_argument("--resume-from-checkpoint", action="store_true",
                        help="Skip events already listed in --checkpoint-file.")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.set_defaults(use_exif_timestamps=True)
    args = parser.parse_args()

    if args.region and (args.country or "").upper() != "USA":
        parser.error("--region requires --country USA")

    if args.confidence is not None and not (0.0 <= args.confidence <= 1.0):
        parser.error("--confidence must be between 0 and 1")
    if args.event_window_seconds < 0:
        parser.error("--event-window-seconds must be >= 0")

    confidence_threshold = resolve_confidence_threshold(
        confidence=args.confidence,
        profile=args.confidence_profile,
    )

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(format=LOG_FMT, level=level, stream=sys.stdout)
    log = logging.getLogger("trailcam_sorter")
    if args.confidence is None:
        log.info(
            "Using confidence profile '%s' (threshold %.2f)",
            args.confidence_profile,
            confidence_threshold,
        )
    else:
        log.info("Using explicit confidence threshold %.2f", confidence_threshold)

    source = Path(args.source).resolve()
    if not source.is_dir():
        log.error("Source folder not found: %s", source)
        sys.exit(1)

    dest_root = Path(args.output).resolve()
    try:
        check_dest_not_a_file(dest_root)
        check_dest_not_in_source(source, dest_root)
    except ValueError as e:
        log.error("%s", e)
        sys.exit(1)

    run_sort(
        source=source,
        dest_root=dest_root,
        confidence=confidence_threshold,
        country=args.country,
        region=args.region,
        move=args.move,
        dry_run=args.dry_run,
        verbose=args.verbose,
        log=log,
        subfolders=not args.no_subfolders,
        sharpness=args.sharpest,
        classifier_backend=args.classifier_backend,
        dedupe_exact=args.dedupe_exact,
        video_match_mode=args.video_match_mode,
        use_exif_timestamps=args.use_exif_timestamps,
        recursive=not args.no_recursive,
        event_window_seconds=args.event_window_seconds,
        report_csv=Path(args.report_csv).resolve() if args.report_csv else None,
        checkpoint_path=Path(args.checkpoint_file).resolve() if args.checkpoint_file else None,
        resume_from_checkpoint=args.resume_from_checkpoint,
    )


if __name__ == "__main__":
    main()
