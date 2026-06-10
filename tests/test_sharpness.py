"""Tests for sharpness-based frame selection."""
import os
import sys
from datetime import datetime
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import group_events, pick_representative, score_sharpness, sort_files


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
