"""Tests for sharpness-based frame selection."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import (
    CONFIDENCE_PROFILES,
    classify_with_backend,
    group_events,
    load_classifier_backend,
    load_checkpoint,
    merge_events_within_window,
    pick_representative,
    RunResult,
    resolve_confidence_threshold,
    score_sharpness,
    save_checkpoint,
    sort_files,
    write_report,
    write_species_csv,
)


def make_image(path: Path, blur_radius: int = 0) -> Path:
    """Write a synthetic grayscale jpg. blur_radius=0 = sharp; >0 = blurry."""
    img = np.random.randint(0, 256, (480, 640), dtype=np.uint8)
    if blur_radius > 0:
        img = cv2.GaussianBlur(img, (blur_radius | 1, blur_radius | 1), 0)
    cv2.imwrite(str(path), img)
    return path


def make_image_with_exif(path: Path, exif_datetime: str) -> Path:
    """Write a jpg with EXIF DateTimeOriginal in YYYY:MM:DD HH:MM:SS format."""
    img = Image.fromarray(np.random.randint(0, 256, (240, 320), dtype=np.uint8))
    exif = Image.Exif()
    exif[36867] = exif_datetime  # DateTimeOriginal
    img.save(path, format="JPEG", exif=exif)
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


def test_sort_files_dry_run_simulates_name_collisions(tmp_path, caplog):
    """dry_run should still allocate unique destination names within one run."""
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    base = make_image(src / "20240615_083012.jpg")
    var1 = make_image(src / "20240615_083012_1.jpg")

    events = {"20240615_083012": [base, var1]}
    rep_map = {"20240615_083012": base}
    predictions = {
        str(base): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9}
    }

    # Seed one existing destination to force suffixing.
    existing_dir = dst / "Odocoileus Virginianus"
    existing_dir.mkdir(parents=True, exist_ok=True)
    existing = existing_dir / "2024-06-15_08-30-12_Odocoileus Virginianus.jpg"
    existing.write_text("existing", encoding="utf-8")

    log = logging.getLogger("test")
    log.setLevel(logging.DEBUG)
    caplog.set_level(logging.DEBUG)
    stats = sort_files(
        events=events,
        predictions=predictions,
        rep_map=rep_map,
        dest_root=dst,
        min_confidence=0.4,
        move=False,
        dry_run=True,
        log=log,
        sharpness=False,
    )

    # Dry-run should not write new files.
    copied = [f for f in dst.rglob("*") if f.is_file()]
    assert copied == [existing]
    # But it should still count both planned operations as sortable output.
    assert sum(stats.values()) == 2

    messages = "\n".join(caplog.messages)
    assert "_2.jpg" in messages
    assert "_3.jpg" in messages


def test_sort_files_dedupe_exact_skips_identical_content(tmp_path):
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    base = make_image(src / "20240615_083012.jpg")
    dup = src / "20240615_083012_1.jpg"
    dup.write_bytes(base.read_bytes())

    events = {"20240615_083012": [base, dup]}
    rep_map = {"20240615_083012": base}
    predictions = {
        str(base): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9}
    }

    dedupe_stats: dict[str, int] = {}
    stats = sort_files(
        events=events,
        predictions=predictions,
        rep_map=rep_map,
        dest_root=dst,
        min_confidence=0.4,
        move=False,
        dry_run=False,
        log=logging.getLogger("test"),
        sharpness=False,
        dedupe_exact=True,
        dedupe_stats=dedupe_stats,
    )

    copied = [f for f in dst.rglob("*") if f.is_file()]
    assert len(copied) == 1
    assert sum(stats.values()) == 1
    assert dedupe_stats["exact_duplicates_skipped"] == 1


def test_video_only_event_matches_nearest_classified_event(tmp_path):
    """Video-only events should match nearest classified image event, not minute bucket order."""
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    deer_img = make_image(src / "20240615_083000.jpg")
    bear_img = make_image(src / "20240615_083050.jpg")
    video_only = src / "20240615_083005.mp4"
    video_only.touch()

    events = {
        "20240615_083000": [deer_img],
        "20240615_083050": [bear_img],
        "20240615_083005": [video_only],
    }
    rep_map = {
        "20240615_083000": deer_img,
        "20240615_083050": bear_img,
    }
    predictions = {
        str(deer_img): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9},
        str(bear_img): {"prediction": "mammalia;ursidae;ursus americanus", "prediction_score": 0.9},
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

    deer_files = [f for f in (dst / "Odocoileus Virginianus").rglob("*.mp4")]
    bear_files = [f for f in (dst / "Ursus Americanus").rglob("*.mp4")]

    assert len(deer_files) == 1
    assert len(bear_files) == 0
    assert stats["Odocoileus Virginianus"] == 2  # deer image + matched video


def test_video_only_event_skips_when_no_nearby_classified_event(tmp_path):
    """Video-only events farther than the matching window should be skipped."""
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    deer_img = make_image(src / "20240615_083000.jpg")
    video_only = src / "20240615_083200.mp4"  # 120 seconds away
    video_only.touch()

    events = {
        "20240615_083000": [deer_img],
        "20240615_083200": [video_only],
    }
    rep_map = {
        "20240615_083000": deer_img,
    }
    predictions = {
        str(deer_img): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9},
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
    assert len(copied) == 1  # only classified image copied
    assert sum(stats.values()) == 1


def test_video_only_event_matches_at_exact_max_gap(tmp_path):
    """Nearest mode should match when gap is exactly 60 seconds."""
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    deer_img = make_image(src / "20240615_083000.jpg")
    video_only = src / "20240615_083100.mp4"  # exactly 60 seconds away
    video_only.touch()

    events = {
        "20240615_083000": [deer_img],
        "20240615_083100": [video_only],
    }
    rep_map = {
        "20240615_083000": deer_img,
    }
    predictions = {
        str(deer_img): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9},
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

    deer_files = [f for f in (dst / "Odocoileus Virginianus").rglob("*.mp4")]
    assert len(deer_files) == 1
    assert stats["Odocoileus Virginianus"] == 2


def test_video_only_event_tie_break_prefers_higher_confidence(tmp_path):
    """When nearest gaps tie, higher-confidence candidate should win."""
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    deer_img = make_image(src / "20240615_083000.jpg")
    bear_img = make_image(src / "20240615_083010.jpg")
    video_only = src / "20240615_083005.mp4"  # equidistant to both image events
    video_only.touch()

    events = {
        "20240615_083000": [deer_img],
        "20240615_083010": [bear_img],
        "20240615_083005": [video_only],
    }
    rep_map = {
        "20240615_083000": deer_img,
        "20240615_083010": bear_img,
    }
    predictions = {
        str(deer_img): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.6},
        str(bear_img): {"prediction": "mammalia;ursidae;ursus americanus", "prediction_score": 0.9},
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

    bear_files = [f for f in (dst / "Ursus Americanus").rglob("*.mp4")]
    deer_files = [f for f in (dst / "Odocoileus Virginianus").rglob("*.mp4")]
    assert len(bear_files) == 1
    assert len(deer_files) == 0
    assert stats["Ursus Americanus"] == 2


def test_video_only_event_minute_mode_uses_legacy_bucket_behavior(tmp_path):
    """minute mode should preserve legacy same-minute overwrite behavior."""
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    deer_img = make_image(src / "20240615_083000.jpg")
    bear_img = make_image(src / "20240615_083050.jpg")
    video_only = src / "20240615_083005.mp4"
    video_only.touch()

    events = {
        "20240615_083000": [deer_img],
        "20240615_083050": [bear_img],
        "20240615_083005": [video_only],
    }
    rep_map = {
        "20240615_083000": deer_img,
        "20240615_083050": bear_img,
    }
    predictions = {
        str(deer_img): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9},
        str(bear_img): {"prediction": "mammalia;ursidae;ursus americanus", "prediction_score": 0.9},
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
        video_match_mode="minute",
    )

    # Legacy behavior maps same-minute video to the last species inserted for that minute.
    bear_files = [f for f in (dst / "Ursus Americanus").rglob("*.mp4")]
    deer_files = [f for f in (dst / "Odocoileus Virginianus").rglob("*.mp4")]

    assert len(bear_files) == 1
    assert len(deer_files) == 0
    assert stats["Ursus Americanus"] == 2  # bear image + matched video


def test_group_events_uses_exif_timestamp_for_non_matching_names(tmp_path):
    exif_img = make_image_with_exif(tmp_path / "DSCF0001.JPG", "2024:06:15 08:30:12")

    events = group_events(tmp_path, recursive=True, use_exif_timestamps=True)

    assert "20240615_083012" in events
    assert exif_img in events["20240615_083012"]


def test_sort_files_uses_exif_timestamp_for_output_naming(tmp_path):
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    exif_img = make_image_with_exif(src / "DSCF0001.JPG", "2024:06:15 08:30:12")
    events = group_events(src, recursive=True, use_exif_timestamps=True)
    rep_map = {
        "20240615_083012": exif_img,
    }
    predictions = {
        str(exif_img): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9},
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

    copied = [f.name for f in dst.rglob("*") if f.is_file()]
    assert any(name.startswith("2024-06-15_08-30-12_Odocoileus Virginianus") for name in copied)
    assert sum(stats.values()) == 1


def test_group_events_falls_back_to_mtime_when_exif_missing(tmp_path):
    img = make_image(tmp_path / "DSCF0002.JPG")
    dt = datetime(2024, 6, 15, 8, 30, 12)
    ts = dt.timestamp()
    os.utime(img, (ts, ts))

    events = group_events(tmp_path, recursive=True, use_exif_timestamps=True)

    assert "20240615_083012" in events
    assert img in events["20240615_083012"]


def test_write_report_includes_run_summary_metrics_and_timings(tmp_path):
    import logging

    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()

    deer_img = make_image(src / "20240615_083000.jpg")
    video_only = src / "20240615_083005.mp4"
    video_only.touch()

    events = {
        "20240615_083000": [deer_img],
        "20240615_083005": [video_only],
    }
    rep_map = {
        "20240615_083000": deer_img,
    }
    predictions = {
        str(deer_img): {"prediction": "mammalia;cervidae;odocoileus virginianus", "prediction_score": 0.9},
    }
    stats = {"Odocoileus Virginianus": 2}
    phase_timings = {"group_events": 0.1, "load_model": 0.2, "inference": 0.3, "sort_files": 0.1}
    video_stats = {
        "video_only_events": 1,
        "video_matched_nearest": 1,
        "video_matched_minute": 0,
        "video_unmatched": 0,
    }
    source_stats = {
        "filename_events": 1,
        "exif_derived_events": 1,
        "mtime_derived_events": 0,
    }

    write_report(
        dest_root=dst,
        events=events,
        predictions=predictions,
        rep_map=rep_map,
        stats=stats,
        log=logging.getLogger("test"),
        phase_timings=phase_timings,
        video_match_stats=video_stats,
        grouping_source_stats=source_stats,
    )

    report_path = dst / "_sort_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["summary"]["classified_image_events"] == 1
    assert report["summary"]["video_only_events"] == 1
    assert report["video_matching"]["video_matched_nearest"] == 1
    assert report["event_key_sources"]["exif_derived_events"] == 1
    assert report["timings_seconds"]["inference"] == 0.3


def test_write_species_csv_writes_sorted_counts_with_percentages(tmp_path):
    import logging

    dst = tmp_path / "dst"
    dst.mkdir()
    csv_path = dst / "summary.csv"
    stats = {
        "Review": 2,
        "Odocoileus Virginianus": 6,
        "Ursus Americanus": 2,
    }

    output = write_species_csv(dst, stats, logging.getLogger("test"), csv_path=csv_path)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert output == csv_path
    assert lines[0] == "category,count,percent_of_sorted"
    assert lines[1].startswith("Odocoileus Virginianus,6,")
    assert lines[2].startswith("Review,2,")
    assert lines[3].startswith("Ursus Americanus,2,")
    assert lines[1].endswith("60.00")


def test_run_result_dataclass_defaults_paths_none():
    result = RunResult(
        source=Path("src"),
        output=Path("out"),
        dry_run=True,
        total_files_scanned=0,
        total_events=0,
        classified_image_events=0,
        video_only_events=0,
        total_files_sorted=0,
        species_counts={},
        review_files=0,
        phase_timings={},
        video_matching={},
        event_key_sources={},
    )

    assert result.exact_duplicates_skipped == 0
    assert result.report_path is None
    assert result.csv_report_path is None
    assert result.checkpoint_path is None


def test_resolve_confidence_threshold_uses_profile_when_value_missing():
    assert resolve_confidence_threshold(None, "conservative") == CONFIDENCE_PROFILES["conservative"]
    assert resolve_confidence_threshold(None, "balanced") == CONFIDENCE_PROFILES["balanced"]
    assert resolve_confidence_threshold(None, "recall") == CONFIDENCE_PROFILES["recall"]


def test_resolve_confidence_threshold_explicit_value_wins():
    assert resolve_confidence_threshold(0.33, "conservative") == 0.33


def test_backend_wrapper_rejects_unknown_backend(tmp_path):
    import logging
    import pytest

    with pytest.raises(ValueError):
        load_classifier_backend("unknown-backend", logging.getLogger("test"))

    with pytest.raises(ValueError):
        classify_with_backend(
            "unknown-backend",
            model=None,
            image_paths=[],
            country=None,
            region=None,
            log=logging.getLogger("test"),
        )


def test_checkpoint_helpers_round_trip(tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"
    keys = {"20240615_083012", "20240615_083013"}

    save_checkpoint(checkpoint_path, keys)
    loaded = load_checkpoint(checkpoint_path)

    assert loaded == keys


def test_checkpoint_helpers_missing_file_returns_empty(tmp_path):
    checkpoint_path = tmp_path / "missing.json"
    loaded = load_checkpoint(checkpoint_path)
    assert loaded == set()


def test_merge_events_within_window_disabled_returns_original(tmp_path):
    img1 = make_image(tmp_path / "20240615_083000.jpg")
    img2 = make_image(tmp_path / "20240615_083020.jpg")
    events = {
        "20240615_083000": [img1],
        "20240615_083020": [img2],
    }
    source_map = {
        "20240615_083000": {"filename"},
        "20240615_083020": {"filename"},
    }

    merged, merged_sources = merge_events_within_window(events, source_map, event_window_seconds=0)

    assert merged == events
    assert merged_sources == source_map


def test_merge_events_within_window_merges_adjacent_keys(tmp_path):
    img1 = make_image(tmp_path / "20240615_083000.jpg")
    img2 = make_image(tmp_path / "20240615_083020.jpg")
    img3 = make_image(tmp_path / "20240615_083300.jpg")

    events = {
        "20240615_083000": [img1],
        "20240615_083020": [img2],
        "20240615_083300": [img3],
    }
    source_map = {
        "20240615_083000": {"filename"},
        "20240615_083020": {"exif"},
        "20240615_083300": {"mtime"},
    }

    merged, merged_sources = merge_events_within_window(events, source_map, event_window_seconds=30)

    assert set(merged.keys()) == {"20240615_083000", "20240615_083300"}
    assert len(merged["20240615_083000"]) == 2
    assert merged_sources is not None
    assert merged_sources["20240615_083000"] == {"filename", "exif"}
