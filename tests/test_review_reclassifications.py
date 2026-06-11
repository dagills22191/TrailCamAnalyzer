import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.apply_review_reclassifications import (
    apply_reclassifications,
    rewrite_sorted_filename,
    sanitize_species_label,
)


def test_rewrite_sorted_filename_replaces_species_label():
    name = "2024-06-15_08-30-12_Review.jpg"
    out = rewrite_sorted_filename(name, "Odocoileus Virginianus")
    assert out == "2024-06-15_08-30-12_Odocoileus Virginianus.jpg"


def test_sanitize_species_label_replaces_invalid_chars():
    assert sanitize_species_label('Bear:Black/Adult') == "Bear_Black_Adult"


def test_apply_reclassifications_moves_files(tmp_path):
    review = tmp_path / "Review"
    out = tmp_path / "Out"
    review.mkdir()
    out.mkdir()

    f1 = review / "2024-06-15_08-30-12_Review.jpg"
    f1.write_text("a", encoding="utf-8")
    f2 = review / "2024-06-15_08-30-20_Review.mp4"
    f2.write_text("b", encoding="utf-8")

    mapping = tmp_path / "map.csv"
    with mapping.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["filename", "new_species"])
        writer.writeheader()
        writer.writerow({"filename": f1.name, "new_species": "Odocoileus Virginianus"})
        writer.writerow({"filename": f2.name, "new_species": "Ursus Americanus"})
        writer.writerow({"filename": "missing.jpg", "new_species": "Review"})

    result = apply_reclassifications(review, out, mapping, move_files=True)

    assert result["moved"] == 2
    assert result["missing"] == 1
    assert not f1.exists()
    assert not f2.exists()
    assert (out / "Odocoileus Virginianus" / "2024-06-15_08-30-12_Odocoileus Virginianus.jpg").exists()
    assert (out / "Ursus Americanus" / "2024-06-15_08-30-20_Ursus Americanus.mp4").exists()
