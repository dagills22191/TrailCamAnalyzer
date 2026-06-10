"""Render a simple local HTML dashboard from _sort_report.json."""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path


def _fmt_seconds(value: object) -> str:
    try:
        return f"{float(value):.2f}"
    except Exception:
        return "0.00"


def _table_rows_from_mapping(mapping: dict[str, object]) -> str:
    rows: list[str] = []
    for key, value in mapping.items():
        rows.append(
            f"<tr><td>{escape(str(key))}</td><td>{escape(str(value))}</td></tr>"
        )
    return "\n".join(rows)


def render_dashboard_html(report: dict[str, object], title: str = "TrailCam Sort Dashboard") -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    species_counts = report.get("species_counts", {}) if isinstance(report.get("species_counts"), dict) else {}
    video_matching = report.get("video_matching", {}) if isinstance(report.get("video_matching"), dict) else {}
    event_key_sources = report.get("event_key_sources", {}) if isinstance(report.get("event_key_sources"), dict) else {}
    timings = report.get("timings_seconds", {}) if isinstance(report.get("timings_seconds"), dict) else {}

    total_sorted = int(report.get("total_files_sorted", 0) or 0)
    top_species = next(iter(species_counts.items()), ("None", 0))

    timing_rows = []
    for key, value in timings.items():
        timing_rows.append(
            f"<tr><td>{escape(str(key))}</td><td>{_fmt_seconds(value)} s</td></tr>"
        )

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f3f6fb;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #475569;
      --accent: #0ea5e9;
      --line: #dbe5f0;
    }}
    body {{ margin: 0; font-family: Segoe UI, Tahoma, sans-serif; background: linear-gradient(180deg, #eef3fb 0%, #f8fafc 100%); color: var(--ink); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    .sub {{ color: var(--muted); margin-bottom: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px; box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04); }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
    .value.small {{ font-size: 20px; }}
    .section {{ margin-top: 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid var(--line); font-size: 14px; }}
    th {{ background: #f8fbff; color: #1e293b; }}
    tr:last-child td {{ border-bottom: none; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>{escape(title)}</h1>
    <div class=\"sub\">Generated: {escape(str(report.get("generated", "unknown")))}</div>

    <div class=\"grid\">
      <div class=\"card\"><div class=\"label\">Files Sorted</div><div class=\"value\">{total_sorted}</div></div>
      <div class=\"card\"><div class=\"label\">Total Events</div><div class=\"value\">{escape(str(report.get("total_events", 0)))}</div></div>
      <div class=\"card\"><div class=\"label\">Classified Image Events</div><div class=\"value\">{escape(str(summary.get("classified_image_events", 0)))}</div></div>
      <div class=\"card\"><div class=\"label\">Top Category</div><div class=\"value small\">{escape(str(top_species[0]))} ({escape(str(top_species[1]))})</div></div>
    </div>

    <div class=\"section\">
      <table>
        <thead><tr><th>Species / Category</th><th>Count</th></tr></thead>
        <tbody>
          {_table_rows_from_mapping(species_counts)}
        </tbody>
      </table>
    </div>

    <div class=\"section\">
      <table>
        <thead><tr><th>Video Matching Metric</th><th>Value</th></tr></thead>
        <tbody>
          {_table_rows_from_mapping(video_matching)}
        </tbody>
      </table>
    </div>

    <div class=\"section\">
      <table>
        <thead><tr><th>Event Key Source</th><th>Value</th></tr></thead>
        <tbody>
          {_table_rows_from_mapping(event_key_sources)}
        </tbody>
      </table>
    </div>

    <div class=\"section\">
      <table>
        <thead><tr><th>Timing Phase</th><th>Duration</th></tr></thead>
        <tbody>
          {''.join(timing_rows)}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an HTML dashboard from a TrailCam _sort_report.json file.")
    parser.add_argument("report_json", help="Path to _sort_report.json")
    parser.add_argument("--output-html", default=None, help="Output HTML path (default: next to report JSON)")
    parser.add_argument("--title", default="TrailCam Sort Dashboard", help="Dashboard title")
    args = parser.parse_args()

    report_path = Path(args.report_json).resolve()
    if not report_path.is_file():
        raise FileNotFoundError(f"Report not found: {report_path}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    html = render_dashboard_html(report, title=args.title)

    output_html = Path(args.output_html).resolve() if args.output_html else report_path.with_name("_sort_dashboard.html")
    output_html.write_text(html, encoding="utf-8")
    print(f"Dashboard written to: {output_html}")


if __name__ == "__main__":
    main()
