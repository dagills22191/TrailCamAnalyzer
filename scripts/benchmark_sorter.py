"""Benchmark TrailCam Sorter performance with hardware metadata.

Examples:
    python scripts/benchmark_sorter.py "E:/TrailCamTestLarge"
    python scripts/benchmark_sorter.py "E:/TrailCamTestLarge" --sample-images 300 --report-json "E:/bench.json"
    python scripts/benchmark_sorter.py "E:/TrailCamTestLarge" --full-inference --no-dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trailcam_sorter import (  # noqa: E402
    classify_images,
    group_events,
    load_model,
    pick_representative,
    sort_files,
)


def get_hardware_info() -> dict:
    info = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.uname().processor,
        "logical_cpu_count": os.cpu_count(),
        "gpu": {
            "backend": None,
            "available": False,
            "device_count": 0,
            "devices": [],
        },
    }

    try:
        import torch

        gpu = info["gpu"]
        gpu["backend"] = "cuda"
        gpu["available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            gpu["device_count"] = torch.cuda.device_count()
            gpu["devices"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    except Exception:
        pass

    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark TrailCam Sorter performance.")
    parser.add_argument("source", help="Source folder to benchmark")
    parser.add_argument("--output", default=None, help="Output root (default: ./benchmark_output)")
    parser.add_argument("--confidence", type=float, default=0.4)
    parser.add_argument("--country", default=None)
    parser.add_argument("--region", default=None)
    parser.add_argument("--video-match-mode", choices=["nearest", "minute"], default="nearest")
    parser.add_argument("--use-exif-timestamps", action="store_true", default=True)
    parser.add_argument("--no-exif-timestamps", action="store_false", dest="use_exif_timestamps")
    parser.add_argument("--recursive", action="store_true", default=True)
    parser.add_argument("--no-recursive", action="store_false", dest="recursive")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--no-dry-run", action="store_false", dest="dry_run")
    parser.add_argument(
        "--sample-images",
        type=int,
        default=200,
        help="Representative images to classify (default: 200). Ignored by --full-inference.",
    )
    parser.add_argument("--full-inference", action="store_true", help="Classify all representative images.")
    parser.add_argument("--report-json", default=None, help="Optional JSON path for benchmark report")
    args = parser.parse_args()

    log = logging.getLogger("benchmark_sorter")
    logging.basicConfig(format="%(asctime)s  %(levelname)-8s  %(message)s", level=logging.INFO)

    source = Path(args.source).resolve()
    if not source.is_dir():
        raise SystemExit(f"Source folder not found: {source}")

    output_root = Path(args.output).resolve() if args.output else (Path.cwd() / "benchmark_output")

    report = {
        "hardware": get_hardware_info(),
        "config": {
            "source": str(source),
            "output": str(output_root),
            "confidence": args.confidence,
            "country": args.country,
            "region": args.region,
            "video_match_mode": args.video_match_mode,
            "use_exif_timestamps": args.use_exif_timestamps,
            "recursive": args.recursive,
            "dry_run": args.dry_run,
            "sample_images": args.sample_images,
            "full_inference": args.full_inference,
        },
        "timings_seconds": {},
        "counts": {},
    }

    t0 = time.perf_counter()
    events = group_events(
        source,
        recursive=args.recursive,
        use_exif_timestamps=args.use_exif_timestamps,
    )
    t_group = time.perf_counter() - t0

    rep_map: dict[str, Path] = {}
    images_to_classify: list[Path] = []
    t1 = time.perf_counter()
    for event_key, files in events.items():
        rep = pick_representative(files, use_sharpness=False)
        if rep:
            rep_map[event_key] = rep
            images_to_classify.append(rep)
    t_rep = time.perf_counter() - t1

    if not images_to_classify:
        raise SystemExit("No representative images found; cannot benchmark inference.")

    selected_images = images_to_classify
    if not args.full_inference:
        selected_images = images_to_classify[: max(args.sample_images, 1)]

    t2 = time.perf_counter()
    model = load_model(log)
    t_model = time.perf_counter() - t2

    t3 = time.perf_counter()
    predictions = classify_images(model, selected_images, args.country, args.region, log)
    t_infer = time.perf_counter() - t3

    # Keep full rep_map/events to benchmark routing and naming behavior.
    t4 = time.perf_counter()
    stats = sort_files(
        events=events,
        predictions=predictions,
        rep_map=rep_map,
        dest_root=output_root,
        min_confidence=args.confidence,
        move=False,
        dry_run=args.dry_run,
        log=log,
        subfolders=True,
        sharpness=False,
        video_match_mode=args.video_match_mode,
    )
    t_sort = time.perf_counter() - t4

    report["timings_seconds"] = {
        "group_events": round(t_group, 3),
        "pick_representatives": round(t_rep, 3),
        "load_model": round(t_model, 3),
        "inference": round(t_infer, 3),
        "sort_files": round(t_sort, 3),
        "total": round(t_group + t_rep + t_model + t_infer + t_sort, 3),
    }
    report["counts"] = {
        "events_total": len(events),
        "representative_images_total": len(images_to_classify),
        "representative_images_classified": len(selected_images),
        "video_only_events": len(events) - len(rep_map),
        "files_sorted_or_planned": int(sum(stats.values())),
    }

    infer_rate = len(selected_images) / max(t_infer, 1e-9)
    print("Benchmark Summary")
    print(f"  CPU: {report['hardware']['processor']}")
    gpu_devices = report["hardware"]["gpu"]["devices"]
    print(f"  GPU: {', '.join(gpu_devices) if gpu_devices else 'None/CPU'}")
    print(f"  Events: {report['counts']['events_total']}")
    print(f"  Representative images classified: {len(selected_images)}")
    print(f"  Inference time: {t_infer:.2f}s ({infer_rate:.2f} images/s)")
    print(f"  Total benchmark time: {report['timings_seconds']['total']:.2f}s")

    if args.report_json:
        report_path = Path(args.report_json).resolve()
    else:
        report_path = Path.cwd() / "benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  Report: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
