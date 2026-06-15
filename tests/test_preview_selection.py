"""Tests for select_preview_candidate — per-batch live-preview image choice."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import select_preview_candidate

DEER = "mammalia;cervidae;odocoileus virginianus"
TURKEY = "aves;galliformes;meleagris gallopavo"


def pred(label, score, fp="x.jpg"):
    return {"filepath": fp, "prediction": label, "prediction_score": score}


def test_picks_highest_confidence_animal():
    batch = [pred(DEER, 0.71, "a.jpg"), pred(TURKEY, 0.93, "b.jpg")]
    assert select_preview_candidate(batch, 0.1)["filepath"] == "b.jpg"


def test_skips_blank_human_vehicle_unknown():
    batch = [
        pred("blank", 0.99, "a.jpg"),
        pred("human", 0.99, "b.jpg"),
        pred("vehicle", 0.99, "c.jpg"),
        pred("animal;mammalia;unknown species", 0.99, "d.jpg"),
        pred("animal", 0.99, "e.jpg"),
        pred("no cv result", 0.99, "f.jpg"),
        pred(DEER, 0.50, "g.jpg"),
    ]
    assert select_preview_candidate(batch, 0.1)["filepath"] == "g.jpg"


def test_skips_below_confidence():
    batch = [pred(DEER, 0.20, "a.jpg"), pred(TURKEY, 0.30, "b.jpg")]
    assert select_preview_candidate(batch, 0.4) is None


def test_all_blank_or_empty_returns_none():
    assert select_preview_candidate([], 0.1) is None
    assert select_preview_candidate([pred("blank", 0.99)], 0.1) is None


def test_returns_single_best_qualifier():
    batch = [pred("blank", 0.99, "a.jpg"), pred(DEER, 0.62, "b.jpg")]
    assert select_preview_candidate(batch, 0.5)["filepath"] == "b.jpg"
