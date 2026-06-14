"""Tests for display_path — normalize a path string to native separators for the GUI."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import display_path


def test_empty_stays_empty():
    assert display_path("") == ""


def test_uses_native_separators():
    out = display_path("C:/Cam/June")
    assert os.sep in out
    if os.sep == "\\":
        # On Windows, forward slashes from the file dialog become backslashes.
        assert "/" not in out
        assert out == r"C:\Cam\June"


def test_already_native_unchanged():
    native = os.path.join("Cam", "June", "clips")
    assert display_path(native) == native
