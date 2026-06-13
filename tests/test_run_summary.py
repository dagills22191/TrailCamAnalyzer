"""Tests for format_run_summary — RunResult -> render-ready summary dict."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from trailcam_sorter import RunResult, format_run_summary


def _result(**overrides):
    """Build a RunResult with sensible defaults, overridable per test."""
    base = dict(
        source=Path("/src"),
        output=Path("/out"),
        dry_run=False,
        total_files_scanned=10,
        total_events=4,
        classified_image_events=3,
        video_only_events=1,
        total_files_sorted=142,
        species_counts={"Deer": 88, "Raccoon": 31, "Blank": 18, "Review": 5},
        review_files=5,
        phase_timings={"total_pipeline": 47.4, "inference": 41.2},
        video_matching={},
        event_key_sources={},
    )
    base.update(overrides)
    return RunResult(**base)


def test_rows_sorted_by_count_descending():
    s = format_run_summary(_result())
    assert s["rows"] == [("Deer", 88), ("Raccoon", 31), ("Blank", 18), ("Review", 5)]
    assert s["total"] == 142


def test_timing_string_rounds_seconds():
    s = format_run_summary(_result())
    assert s["timing"] == "time: 47s (inference 41s)"


def test_report_path_listed_when_set():
    s = format_run_summary(_result(report_path=Path("/out/_sort_report.json")))
    assert s["reports"] == ["_sort_report.json"]


def test_csv_report_listed_when_set():
    s = format_run_summary(_result(
        report_path=Path("/out/_sort_report.json"),
        csv_report_path=Path("/out/counts.csv"),
    ))
    assert s["reports"] == ["_sort_report.json", "counts.csv"]


def test_no_reports_when_unset():
    s = format_run_summary(_result())
    assert s["reports"] == []


def test_dry_run_sets_banner():
    s = format_run_summary(_result(dry_run=True))
    assert s["banner"] == ("dry_run", "DRY RUN — no files were moved.")


def test_non_dry_run_has_no_banner():
    assert format_run_summary(_result())["banner"] is None


def test_empty_result_with_missing_timing_keys_does_not_raise():
    # Mirrors the no-events / video-only early returns: phase_timings lacks
    # 'inference' and 'total_pipeline'.
    s = format_run_summary(_result(
        species_counts={},
        total_files_sorted=0,
        phase_timings={"group_events": 0.01},
    ))
    assert s["rows"] == []
    assert s["total"] == 0
    assert s["timing"] == "time: 0s (inference 0s)"
