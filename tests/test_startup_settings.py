"""Tests for resolve_startup_settings — loaded config dict -> GUI field values."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import resolve_startup_settings


def test_empty_config_yields_defaults():
    s = resolve_startup_settings({})
    assert s["last_source"] == ""
    assert s["last_output"] == str(Path.home() / "TrailCamAnimals")
    assert "advanced_mode" not in s
    assert s["recursive"] is True
    assert s["country"] == ""
    assert s["region"] == ""
    assert s["confidence"] == 0.4
    assert s["species_subfolders"] is True
    assert s["sharpness"] is False
    assert s["exif_fallback"] is True
    assert s["move"] is False
    assert s["dry_run"] is False


def test_persisted_values_restored():
    cfg = {
        "last_source": r"D:\Cam\June",
        "last_output": r"D:\Sorted",
        "recursive": False,
        "country": "USA",
        "region": "Michigan",
        "confidence": 0.6,
        "species_subfolders": False,
        "sharpness": True,
        "exif_fallback": False,
    }
    s = resolve_startup_settings(cfg)
    assert s["last_source"] == r"D:\Cam\June"
    assert s["last_output"] == r"D:\Sorted"
    assert s["recursive"] is False
    assert s["country"] == "USA"
    assert s["region"] == "Michigan"
    assert s["confidence"] == 0.6
    assert s["species_subfolders"] is False
    assert s["sharpness"] is True
    assert s["exif_fallback"] is False


def test_move_and_dry_run_always_off_even_if_persisted():
    s = resolve_startup_settings({"move": True, "dry_run": True})
    assert s["move"] is False
    assert s["dry_run"] is False


def test_confidence_clamped_to_slider_range():
    assert resolve_startup_settings({"confidence": 5.0})["confidence"] == 0.9
    assert resolve_startup_settings({"confidence": 0.0})["confidence"] == 0.1


def test_confidence_non_numeric_falls_back_to_default():
    assert resolve_startup_settings({"confidence": "high"})["confidence"] == 0.4


def test_region_cleared_when_country_not_usa():
    s = resolve_startup_settings({"country": "CAN", "region": "Michigan"})
    assert s["region"] == ""


def test_region_kept_when_country_usa():
    s = resolve_startup_settings({"country": "USA", "region": "Ohio"})
    assert s["region"] == "Ohio"


def test_corrupt_boolean_coerced():
    # A hand-edited or legacy config may store booleans as strings/ints.
    s = resolve_startup_settings({"species_subfolders": 0, "recursive": 0})
    assert s["species_subfolders"] is False
    assert s["recursive"] is False


def test_theme_defaults_to_dark_when_absent():
    assert resolve_startup_settings({})["theme"] == "dark"


def test_theme_light_is_restored():
    assert resolve_startup_settings({"theme": "light"})["theme"] == "light"


def test_theme_dark_is_restored():
    assert resolve_startup_settings({"theme": "dark"})["theme"] == "dark"


def test_theme_unknown_value_falls_back_to_dark():
    assert resolve_startup_settings({"theme": "rainbow"})["theme"] == "dark"
    assert resolve_startup_settings({"theme": 123})["theme"] == "dark"
