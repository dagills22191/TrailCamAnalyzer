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
