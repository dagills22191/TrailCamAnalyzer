"""Tests for batched classify_images — chunking, cancel, progress, merge."""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import logging

from trailcam_sorter import classify_images, INFERENCE_BATCH_SIZE, Cancelled

LOG = logging.getLogger("test")


class FakeModel:
    """Records each predict() call's instance count and returns canned preds."""
    def __init__(self):
        self.batch_sizes = []

    def predict(self, instances_dict=None, **kwargs):
        instances = instances_dict["instances"]
        self.batch_sizes.append(len(instances))
        return {
            "predictions": [
                {"filepath": inst["filepath"], "prediction": "Deer"}
                for inst in instances
            ]
        }


def _paths(n):
    return [Path(f"/img/{i}.jpg") for i in range(n)]


def test_merges_predictions_across_batches():
    model = FakeModel()
    paths = _paths(120)
    result = classify_images(model, paths, None, None, LOG)
    assert len(result) == 120
    for p in paths:
        assert result[str(p)]["prediction"] == "Deer"


def test_chunks_at_batch_size():
    model = FakeModel()
    classify_images(model, _paths(120), None, None, LOG)
    # 120 with INFERENCE_BATCH_SIZE == 50 -> 50, 50, 20
    assert INFERENCE_BATCH_SIZE == 50
    assert model.batch_sizes == [50, 50, 20]


def test_empty_input_makes_no_predict_call():
    model = FakeModel()
    result = classify_images(model, [], None, None, LOG)
    assert result == {}
    assert model.batch_sizes == []


def test_cancel_between_batches_raises_and_stops():
    model = FakeModel()
    event = threading.Event()
    event.set()  # already cancelled -> should raise before any predict
    try:
        classify_images(model, _paths(120), None, None, LOG, cancel_event=event)
        assert False, "expected Cancelled"
    except Cancelled:
        pass
    assert model.batch_sizes == []


def test_progress_callback_reaches_one():
    model = FakeModel()
    seen = []
    classify_images(
        model, _paths(120), None, None, LOG,
        progress_callback=lambda f: seen.append(f),
    )
    assert seen, "progress_callback should be called"
    assert seen == sorted(seen), "fractions must be non-decreasing"
    assert seen[-1] == 1.0
    assert all(0.0 <= f <= 1.0 for f in seen)
