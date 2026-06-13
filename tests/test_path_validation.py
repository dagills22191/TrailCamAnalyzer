"""Tests for output-path safety validation (dest-in-source guard)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import (
    check_dest_not_in_source,
    check_dest_not_a_file,
    open_in_file_manager,
)


def test_dest_existing_file_is_rejected(tmp_path):
    dest = tmp_path / "out.txt"
    dest.write_text("not a folder")
    with pytest.raises(ValueError):
        check_dest_not_a_file(dest.resolve())


def test_dest_nonexistent_path_is_allowed(tmp_path):
    dest = tmp_path / "out"  # does not exist yet
    check_dest_not_a_file(dest.resolve())


def test_dest_existing_dir_is_allowed(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    check_dest_not_a_file(dest.resolve())


def test_version_constant_is_defined():
    import re
    import trailcam_sorter
    assert re.fullmatch(r"\d+\.\d+\.\d+", trailcam_sorter.__version__)


def test_dest_nested_inside_source_is_rejected(tmp_path):
    source = tmp_path / "cam"
    dest = source / "sorted"
    source.mkdir()
    with pytest.raises(ValueError):
        check_dest_not_in_source(source.resolve(), dest.resolve())


def test_dest_equal_to_source_is_rejected(tmp_path):
    source = tmp_path / "cam"
    source.mkdir()
    with pytest.raises(ValueError):
        check_dest_not_in_source(source.resolve(), source.resolve())


def test_dest_outside_source_is_allowed(tmp_path):
    source = tmp_path / "cam"
    dest = tmp_path / "out"
    source.mkdir()
    # Should not raise.
    check_dest_not_in_source(source.resolve(), dest.resolve())


def test_dest_as_parent_of_source_is_allowed(tmp_path):
    source = tmp_path / "cam" / "burst"
    dest = tmp_path / "cam"
    source.mkdir(parents=True)
    # Writing to a parent of source is allowed; only dest-in-source is dangerous.
    check_dest_not_in_source(source.resolve(), dest.resolve())


def test_open_in_file_manager_rejects_missing_path(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(ValueError):
        open_in_file_manager(missing.resolve())


def test_open_in_file_manager_rejects_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(ValueError):
        open_in_file_manager(f.resolve())
