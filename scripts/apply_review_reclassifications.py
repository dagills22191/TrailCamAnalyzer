"""Apply manual reclassifications from a CSV to files in a Review folder."""

from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path

FILENAME_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_(.+?)(\.[^.]+)$")


def sanitize_species_label(label: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", label).strip() or "Review"


def rewrite_sorted_filename(original_name: str, new_species: str) -> str:
    """Rewrite yyyy-mm-dd_HH-MM-SS_species.ext with a new species label."""
    m = FILENAME_PATTERN.match(original_name)
    safe = sanitize_species_label(new_species)
    if not m:
        stem, ext = Path(original_name).stem, Path(original_name).suffix
        return f"{stem}_{safe}{ext}"
    prefix, _, ext = m.groups()
    return f"{prefix}_{safe}{ext}"


def apply_reclassifications(
    review_folder: Path,
    output_root: Path,
    mapping_csv: Path,
    move_files: bool = True,
) -> dict[str, int]:
    """Apply filename->species mapping and move/copy files out of Review."""
    action = shutil.move if move_files else shutil.copy2
    moved = 0
    missing = 0

    with mapping_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = (row.get("filename") or "").strip()
            species = (row.get("new_species") or "").strip()
            if not filename or not species:
                continue

            src = review_folder / filename
            if not src.is_file():
                missing += 1
                continue

            safe_species = sanitize_species_label(species)
            target_dir = output_root / safe_species
            target_dir.mkdir(parents=True, exist_ok=True)

            target_name = rewrite_sorted_filename(src.name, safe_species)
            dst = target_dir / target_name
            i = 2
            while dst.exists():
                dst = target_dir / f"{Path(target_name).stem}_{i}{Path(target_name).suffix}"
                i += 1

            action(str(src), str(dst))
            moved += 1

    return {"moved": moved, "missing": missing}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply manual Review reclassifications from CSV.")
    parser.add_argument("review_folder", help="Path to Review folder containing files to reclassify")
    parser.add_argument("output_root", help="Root output folder containing species subfolders")
    parser.add_argument("mapping_csv", help="CSV with columns: filename,new_species")
    parser.add_argument("--copy", action="store_true", help="Copy files instead of moving them")
    args = parser.parse_args()

    review_folder = Path(args.review_folder).resolve()
    output_root = Path(args.output_root).resolve()
    mapping_csv = Path(args.mapping_csv).resolve()

    if not review_folder.is_dir():
        raise FileNotFoundError(f"Review folder not found: {review_folder}")
    if not mapping_csv.is_file():
        raise FileNotFoundError(f"Mapping CSV not found: {mapping_csv}")

    result = apply_reclassifications(
        review_folder=review_folder,
        output_root=output_root,
        mapping_csv=mapping_csv,
        move_files=not args.copy,
    )
    print(f"Moved/Copied: {result['moved']}")
    print(f"Missing entries: {result['missing']}")


if __name__ == "__main__":
    main()
