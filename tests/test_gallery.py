import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.gallery import build_gallery_index, write_gallery_reports
from leancapsule.audit import audit_directory
from leancapsule.schema import validate_json_schema, validate_manifest


class GalleryTest(unittest.TestCase):
    def test_release_audit_passes(self):
        result = audit_directory(ROOT / "capsules")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["reviewed"], result["total"])

    def test_gallery_meets_coverage_requirements(self):
        index = build_gallery_index(ROOT / "capsules")
        self.assertTrue(index["ok"], index)
        self.assertGreaterEqual(index["total"], 12)

    def test_all_manifests_have_required_fields_and_no_absolute_source_path(self):
        for path in (ROOT / "capsules").rglob("capsule.json"):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(validate_manifest(manifest), [])
            self.assertEqual(validate_json_schema(manifest), [])
            self.assertNotIn(str(ROOT).lower(), json.dumps(manifest, ensure_ascii=False).lower())

    def test_manual_review_ledger_covers_gallery(self):
        with (ROOT / "capsules" / "MANUAL_REVIEW.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        ids = {json.loads(path.read_text(encoding="utf-8"))["capsule_id"] for path in (ROOT / "capsules").rglob("capsule.json")}
        self.assertEqual(ids, {row["capsule_id"] for row in rows})

    def test_gallery_reports_are_reproducible(self):
        index = build_gallery_index(ROOT / "capsules")
        out = ROOT / "tests" / ".gallery-test.json"
        try:
            write_gallery_reports(index, out)
            self.assertTrue(out.with_suffix(".csv").exists())
            self.assertTrue(out.with_suffix(".md").exists())
        finally:
            for path in (out, out.with_suffix(".csv"), out.with_suffix(".md")):
                if path.exists():
                    path.unlink()

    def test_audit_rejects_sp1_unsafe_inductive(self):
        with tempfile.TemporaryDirectory() as temp:
            gallery = Path(temp) / "capsules"
            shutil.copytree(ROOT / "capsules", gallery)
            target = next(gallery.rglob("Capsule.lean"))
            target.write_text(
                (ROOT / "benchmarks" / "security" / "unsafe_inductive_false.lean").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            result = audit_directory(gallery)
            self.assertFalse(result["ok"])
            self.assertTrue(any("不安全声明" in error for error in result["errors"]))
