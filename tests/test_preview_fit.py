"""Tests for fit_preview_size — scaling the live preview to the Preview tab."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import fit_preview_size


def test_wide_image_limited_by_width():
    assert fit_preview_size(1600, 900, 800, 800) == (800, 450)


def test_tall_box_limited_by_height():
    assert fit_preview_size(1600, 900, 2000, 450) == (800, 450)


def test_never_enlarges_small_image():
    assert fit_preview_size(640, 480, 2000, 2000) == (640, 480)


def test_keeps_aspect_ratio():
    w, h = fit_preview_size(1600, 1200, 1000, 500)
    assert (w, h) == (667, 500)


def test_degenerate_box_returns_source_size():
    assert fit_preview_size(640, 480, 0, 300) == (640, 480)


def test_tiny_box_never_zero():
    assert fit_preview_size(1600, 900, 1, 1) == (1, 1)
