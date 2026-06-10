"""Tests for event grouping — filename pattern, EXIF fallback, recursive flag."""
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import cv2
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import group_events, _event_key_from_exif, _event_key_from_mtime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_jpeg(path: Path) -> Path:
    """Write a minimal valid JPEG with no EXIF."""
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    cv2.imwrite(str(path), img)
    return path


def make_jpeg_with_exif(path: Path, dt: datetime) -> Path:
    """Write a JPEG with DateTime (tag 306) set via Pillow's EXIF writer."""
    img = Image.new("RGB", (8, 8), color=0)
    exif = img.getexif()
    exif[306] = dt.strftime("%Y:%m:%d %H:%M:%S")  # DateTime (IFD0)
    img.save(str(path), exif=exif.tobytes())
    return path


# ---------------------------------------------------------------------------
# _event_key_from_exif
# ---------------------------------------------------------------------------

def test_exif_key_returns_correct_format(tmp_path):
    dt = datetime(2024, 6, 15, 8, 30, 12)
    p = make_jpeg_with_exif(tmp_path / "shot.jpg", dt)
    key = _event_key_from_exif(p)
    assert key == "20240615_083012"


def test_exif_key_returns_none_for_no_exif(tmp_path):
    p = make_jpeg(tmp_path / "noexif.jpg")
    assert _event_key_from_exif(p) is None


def test_exif_key_returns_none_for_missing_file():
    assert _event_key_from_exif(Path("/nonexistent/file.jpg")) is None


# ---------------------------------------------------------------------------
# _event_key_from_mtime
# ---------------------------------------------------------------------------

def test_mtime_key_returns_yyyymmdd_format(tmp_path):
    p = tmp_path / "video.mp4"
    p.touch()
    key = _event_key_from_mtime(p)
    assert len(key) == 15                     # YYYYMMDD_HHMMSS
    assert key[8] == "_"
    datetime.strptime(key, "%Y%m%d_%H%M%S")  # raises if format is wrong


# ---------------------------------------------------------------------------
# group_events — filename pattern
# ---------------------------------------------------------------------------

def test_group_events_filename_pattern(tmp_path):
    make_jpeg(tmp_path / "20240615_083012.jpg")
    make_jpeg(tmp_path / "20240615_083012_1.jpg")
    (tmp_path / "20240615_083012.mp4").touch()
    events = group_events(tmp_path)
    assert "20240615_083012" in events
    assert len(events["20240615_083012"]) == 3


def test_group_events_multiple_events(tmp_path):
    make_jpeg(tmp_path / "20240615_083012.jpg")
    make_jpeg(tmp_path / "20240615_091500.jpg")
    events = group_events(tmp_path)
    assert len(events) == 2


# ---------------------------------------------------------------------------
# group_events — EXIF fallback
# ---------------------------------------------------------------------------

def test_group_events_exif_fallback(tmp_path):
    dt = datetime(2024, 6, 15, 8, 30, 12)
    make_jpeg_with_exif(tmp_path / "DSCF0001.JPG", dt)
    events = group_events(tmp_path)
    assert "20240615_083012" in events


def test_group_events_exif_groups_same_second(tmp_path):
    dt = datetime(2024, 6, 15, 8, 30, 12)
    make_jpeg_with_exif(tmp_path / "DSCF0001.JPG", dt)
    make_jpeg_with_exif(tmp_path / "DSCF0002.JPG", dt)
    events = group_events(tmp_path)
    assert len(events) == 1
    assert len(list(events.values())[0]) == 2


def test_group_events_mtime_fallback_for_video(tmp_path):
    v = tmp_path / "MOV0001.mp4"
    v.touch()
    events = group_events(tmp_path)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# group_events — recursive flag
# ---------------------------------------------------------------------------

def test_group_events_recursive_finds_subfolders(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    make_jpeg(tmp_path / "20240615_083012.jpg")
    make_jpeg(sub / "20240616_091500.jpg")
    events = group_events(tmp_path, recursive=True)
    assert len(events) == 2


def test_group_events_non_recursive_ignores_subfolders(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    make_jpeg(tmp_path / "20240615_083012.jpg")
    make_jpeg(sub / "20240616_091500.jpg")
    events = group_events(tmp_path, recursive=False)
    assert len(events) == 1
    assert "20240615_083012" in events


def test_group_events_skips_unsupported_extensions(tmp_path):
    (tmp_path / "document.pdf").touch()
    (tmp_path / "notes.txt").touch()
    make_jpeg(tmp_path / "20240615_083012.jpg")
    events = group_events(tmp_path)
    assert len(events) == 1
