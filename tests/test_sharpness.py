"""Tests for sharpness-based frame selection."""
import sys
from pathlib import Path
import tempfile
import numpy as np
import cv2
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import score_sharpness, pick_representative, sort_files, VIDEO_EXTS


def make_image(path: Path, blur_radius: int = 0) -> Path:
    """Write a synthetic grayscale jpg. blur_radius=0 = sharp; >0 = blurry."""
    img = np.random.randint(0, 256, (480, 640), dtype=np.uint8)
    if blur_radius > 0:
        img = cv2.GaussianBlur(img, (blur_radius | 1, blur_radius | 1), 0)
    cv2.imwrite(str(path), img)
    return path


# --- score_sharpness ---

def test_score_sharpness_returns_float(tmp_path):
    p = make_image(tmp_path / "20240615_083012.jpg")
    result = score_sharpness(p)
    assert isinstance(result, float)


def test_score_sharpness_missing_file_returns_zero():
    result = score_sharpness(Path("/nonexistent/image.jpg"))
    assert result == 0.0


def test_score_sharpness_sharp_beats_blurry(tmp_path):
    sharp = make_image(tmp_path / "sharp.jpg", blur_radius=0)
    blurry = make_image(tmp_path / "blurry.jpg", blur_radius=51)
    assert score_sharpness(sharp) > score_sharpness(blurry)


# --- pick_representative with use_sharpness ---

def test_pick_representative_sharpness_off_returns_base_image(tmp_path):
    """Without sharpness, returns base image (no variant suffix)."""
    base  = make_image(tmp_path / "20240615_083012.jpg")
    var1  = make_image(tmp_path / "20240615_083012_1.jpg", blur_radius=0)
    result = pick_representative([base, var1], use_sharpness=False)
    assert result == base


def test_pick_representative_sharpness_on_returns_sharpest(tmp_path):
    """With sharpness, returns the sharpest image regardless of variant order."""
    blurry_base = make_image(tmp_path / "20240615_083012.jpg",   blur_radius=51)
    sharp_var   = make_image(tmp_path / "20240615_083012_1.jpg", blur_radius=0)
    result = pick_representative([blurry_base, sharp_var], use_sharpness=True)
    assert result == sharp_var


def test_pick_representative_single_image_ignores_sharpness(tmp_path):
    """Single image event: sharpness flag is irrelevant, image is returned."""
    only = make_image(tmp_path / "20240615_083012.jpg")
    assert pick_representative([only], use_sharpness=True) == only


def test_pick_representative_video_only_returns_none(tmp_path):
    video = tmp_path / "20240615_083012.mp4"
    video.touch()
    assert pick_representative([video], use_sharpness=True) is None


# --- sort_files with sharpness=True ---

def test_sort_files_sharpness_copies_only_rep_and_video(tmp_path):
    """sharpness=True: only the representative image and videos are copied."""
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    base  = make_image(src / "20240615_083012.jpg",   blur_radius=0)
    var1  = make_image(src / "20240615_083012_1.jpg", blur_radius=51)
    video = src / "20240615_083012.mp4"
    video.touch()

    events  = {"20240615_083012": [base, var1, video]}
    rep_map = {"20240615_083012": base}
    predictions = {
        str(base): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9}
    }

    log = logging.getLogger("test")
    stats = sort_files(
        events=events,
        predictions=predictions,
        rep_map=rep_map,
        dest_root=dst,
        min_confidence=0.4,
        move=False,
        dry_run=False,
        log=log,
        sharpness=True,
    )

    copied = list(dst.rglob("*"))
    copied_names = [f.name for f in copied if f.is_file()]

    assert len(copied_names) == 2
    assert not any("_1" in name for name in copied_names)
    assert any(name.endswith(".mp4") for name in copied_names)
    assert sum(stats.values()) == 2


def test_sort_files_no_sharpness_copies_all(tmp_path):
    """sharpness=False (default): all burst files are copied as before."""
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    base  = make_image(src / "20240615_083012.jpg",   blur_radius=0)
    var1  = make_image(src / "20240615_083012_1.jpg", blur_radius=51)
    video = src / "20240615_083012.mp4"
    video.touch()

    events  = {"20240615_083012": [base, var1, video]}
    rep_map = {"20240615_083012": base}
    predictions = {
        str(base): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9}
    }

    log = logging.getLogger("test")
    stats = sort_files(
        events=events,
        predictions=predictions,
        rep_map=rep_map,
        dest_root=dst,
        min_confidence=0.4,
        move=False,
        dry_run=False,
        log=log,
        sharpness=False,
    )

    copied = [f for f in dst.rglob("*") if f.is_file()]
    assert len(copied) == 3
    assert sum(stats.values()) == 3
