"""Compare legacy minute matching vs nearest-time matching for video-only events.

Usage:
    python scripts/compare_video_match_modes.py "E:/TrailCamTest"
    python scripts/compare_video_match_modes.py "E:/TrailCamTest" --confidence 0.4 --csv out.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trailcam_sorter import (
    VIDEO_MATCH_MAX_GAP_SECONDS,
    classify_images,
    group_events,
    load_model,
    parse_event_key_timestamp,
    pick_representative,
    sanitize_label,
)


def build_assignments(
    events: dict[str, list[Path]],
    rep_map: dict[str, Path],
    predictions: dict[str, dict],
    min_confidence: float,
    mode: str,
) -> dict[str, str | None]:
    """Return {video_only_event_key: assigned_species_or_none} for a mode."""
    if mode not in {"minute", "nearest"}:
        raise ValueError(f"Unsupported mode: {mode}")

    minute_species: dict[str, str] = {}
    candidates: list[tuple[object, str, float]] = []

    for event_key, rep in rep_map.items():
        pred = predictions.get(str(rep), {})
        label = pred.get("prediction", "")
        score = pred.get("prediction_score", 0.0) or 0.0
        species = sanitize_label(label) if label else ""
        ts = parse_event_key_timestamp(event_key)
        if ts and species and species.lower() != "blank" and score >= min_confidence and "unknown" not in label.lower():
            minute_species[event_key[:13]] = species
            candidates.append((ts, species, float(score)))

    assignments: dict[str, str | None] = {}
    for event_key in events:
        if event_key in rep_map:
            continue

        if mode == "minute":
            assignments[event_key] = minute_species.get(event_key[:13])
            continue

        species_name = None
        event_ts = parse_event_key_timestamp(event_key)
        if event_ts and candidates:
            ranked = sorted(
                candidates,
                key=lambda c: (abs((c[0] - event_ts).total_seconds()), -c[2]),
            )
            best_ts, best_species, _ = ranked[0]
            gap_s = abs((best_ts - event_ts).total_seconds())
            if gap_s <= VIDEO_MATCH_MAX_GAP_SECONDS:
                species_name = best_species

        assignments[event_key] = species_name

    return assignments


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare video-only assignments between minute and nearest modes.")
    parser.add_argument("source", help="Folder containing trail-cam files")
    parser.add_argument("--confidence", type=float, default=0.4, help="Minimum confidence threshold (default: 0.4)")
    parser.add_argument("--country", default=None, help="ISO alpha-3 country code for geofencing (e.g. USA)")
    parser.add_argument("--region", default=None, help="US region code for geofencing (e.g. VA)")
    parser.add_argument("--csv", default=None, help="Optional CSV output path for per-event comparison")
    parser.add_argument("--sample-limit", type=int, default=20, help="How many changed events to print (default: 20)")
    args = parser.parse_args()

    log = logging.getLogger("compare_video_match_modes")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")

    source = Path(args.source).resolve()
    if not source.is_dir():
        raise SystemExit(f"Source folder not found: {source}")

    events = group_events(source, recursive=True)
    rep_map: dict[str, Path] = {}
    images_to_classify: list[Path] = []
    for event_key, files in events.items():
        rep = pick_representative(files, use_sharpness=False)
        if rep:
            rep_map[event_key] = rep
            images_to_classify.append(rep)

    if not images_to_classify:
        raise SystemExit("No representative images found; cannot compare modes.")

    log.info("Found %d events (%d video-only).", len(events), len(events) - len(rep_map))
    model = load_model(log)
    predictions = classify_images(model, images_to_classify, args.country, args.region, log)

    old_assignments = build_assignments(events, rep_map, predictions, args.confidence, mode="minute")
    new_assignments = build_assignments(events, rep_map, predictions, args.confidence, mode="nearest")

    changed: list[tuple[str, str | None, str | None]] = []
    unchanged_same = 0
    unchanged_none = 0
    old_only = 0
    new_only = 0

    for event_key in sorted(old_assignments):
        old_sp = old_assignments[event_key]
        new_sp = new_assignments[event_key]
        if old_sp == new_sp:
            if old_sp is None:
                unchanged_none += 1
            else:
                unchanged_same += 1
            continue

        if old_sp and not new_sp:
            old_only += 1
        elif new_sp and not old_sp:
            new_only += 1

        changed.append((event_key, old_sp, new_sp))

    transitions = Counter((o or "<none>", n or "<none>") for _, o, n in changed)

    print(f"events_total={len(events)}")
    print(f"events_with_images={len(rep_map)}")
    print(f"video_only_events={len(old_assignments)}")
    print(f"video_match_window_seconds={VIDEO_MATCH_MAX_GAP_SECONDS}")
    print(f"unchanged_same_species={unchanged_same}")
    print(f"unchanged_both_unassigned={unchanged_none}")
    print(f"changed={len(changed)}")
    print(f"changed_old_only={old_only}")
    print(f"changed_new_only={new_only}")

    print("\nTop transitions:")
    for (old_name, new_name), count in transitions.most_common(20):
        print(f"  {old_name} -> {new_name}: {count}")

    print("\nSample changed events:")
    for event_key, old_sp, new_sp in changed[: max(args.sample_limit, 0)]:
        print(f"  {event_key}: old={old_sp or '<none>'} | new={new_sp or '<none>'}")

    if args.csv:
        csv_path = Path(args.csv).resolve()
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["event_key", "old_mode_minute", "new_mode_nearest", "changed"])
            for event_key in sorted(old_assignments):
                old_sp = old_assignments[event_key]
                new_sp = new_assignments[event_key]
                writer.writerow([event_key, old_sp or "", new_sp or "", old_sp != new_sp])
        print(f"\nCSV written: {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
