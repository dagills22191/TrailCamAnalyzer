import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.render_sort_dashboard import render_dashboard_html


def test_render_dashboard_html_contains_core_sections():
    report = {
        "generated": "2026-06-10T12:00:00",
        "total_events": 10,
        "total_files_sorted": 12,
        "summary": {
            "classified_image_events": 8,
            "video_only_events": 2,
            "exif_derived_events": 1,
            "mtime_derived_events": 0,
        },
        "species_counts": {
            "Odocoileus Virginianus": 9,
            "Review": 3,
        },
        "video_matching": {
            "video_only_events": 2,
            "video_matched_nearest": 2,
            "video_matched_minute": 0,
            "video_unmatched": 0,
        },
        "event_key_sources": {
            "filename_events": 9,
            "exif_derived_events": 1,
            "mtime_derived_events": 0,
        },
        "timings_seconds": {
            "group_events": 0.2,
            "load_model": 1.1,
            "inference": 12.3,
            "sort_files": 0.4,
            "total_pipeline": 14.0,
        },
    }

    html = render_dashboard_html(report)

    assert "TrailCam Sort Dashboard" in html
    assert "Files Sorted" in html
    assert "Odocoileus Virginianus" in html
    assert "Video Matching Metric" in html
    assert "Timing Phase" in html


def test_render_dashboard_main_like_write(tmp_path):
    report_path = tmp_path / "_sort_report.json"
    output_path = tmp_path / "_sort_dashboard.html"

    report_path.write_text(
        json.dumps(
            {
                "generated": "2026-06-10T12:00:00",
                "total_events": 1,
                "total_files_sorted": 1,
                "summary": {"classified_image_events": 1},
                "species_counts": {"Review": 1},
                "video_matching": {},
                "event_key_sources": {},
                "timings_seconds": {},
            }
        ),
        encoding="utf-8",
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    html = render_dashboard_html(report)
    output_path.write_text(html, encoding="utf-8")

    assert output_path.exists()
    text = output_path.read_text(encoding="utf-8")
    assert "Review" in text
