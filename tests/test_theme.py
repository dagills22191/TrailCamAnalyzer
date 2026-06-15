"""Tests for the centralized THEME palette and color resolution helper."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import THEME, _resolve_mode_color

# Every role used by the GUI must exist so a missed key fails loudly here
# rather than as a runtime AttributeError when building a widget.
REQUIRED_ROLES = {
    "bg", "surface", "input", "border", "accent", "accent_hi", "text",
    "dim", "muted", "cancel", "cancel_hi", "close_hi", "header",
    "header_title", "header_sub", "log_text", "warn", "error",
}


def test_all_required_roles_present():
    assert REQUIRED_ROLES.issubset(THEME.keys())


def test_every_role_is_a_light_dark_pair_of_nonempty_strings():
    for role, value in THEME.items():
        assert isinstance(value, tuple), f"{role} is not a tuple"
        assert len(value) == 2, f"{role} is not a 2-tuple"
        light, dark = value
        assert isinstance(light, str) and light.strip(), f"{role} light empty"
        assert isinstance(dark, str) and dark.strip(), f"{role} dark empty"


def test_resolve_mode_color_picks_by_mode():
    assert _resolve_mode_color(("#aaa", "#bbb"), mode="light") == "#aaa"
    assert _resolve_mode_color(("#aaa", "#bbb"), mode="dark") == "#bbb"


def test_resolve_mode_color_passes_through_plain_strings():
    # Plain strings (e.g. "white") are mode-independent and returned as-is.
    assert _resolve_mode_color("white", mode="light") == "white"
    assert _resolve_mode_color("white", mode="dark") == "white"
