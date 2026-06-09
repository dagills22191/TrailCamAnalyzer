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
