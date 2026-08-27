import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.gallery import build_gallery_index, write_gallery_reports
from leancapsule.audit import audit_directory
from leancapsule.schema import validate_json_schema, validate_manifest


def write_auditable_capsule(root: Path, *, review_values="true,true,true,true", environment=None) -> Path:
    capsule = root / "demo"
    capsule.mkdir()
    for name in ("Capsule.lean", "expected-diagnostic.txt", "README.md", "replay.ps1", "replay.sh"):
        (capsule / name).write_text("test\n", encoding="utf-8")
    (capsule / "lean-toolchain").write_text("test-toolchain\n", encoding="utf-8")
    manifest = {
        "schema_version": "leancapsule.v0.1",
        "capsule_id": "demo",
        "target": {"source_file": "Demo.lean", "selection_mode": "lines", "lines": "1:1"},
        "environment": environment or {
            "lean_toolchain": "test-toolchain",
            "lake_manifest_present": False,
            "lakefile_present": False,
            "local_files": [],
            "dependency_project": None,
        },
        "expected": {"compile_ok": False, "category": "compile_error", "diagnostic_key": "compile_error | test"},
        "taxonomy": "Name / import",
        "source_kind": "std",
        "provenance": {"license": "MIT", "source_url": None, "notes": "test"},
        "replay": {"file": "Capsule.lean", "command": "python -m leancapsule replay ."},
    }
    (capsule / "capsule.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "MANUAL_REVIEW.csv").write_text(
        "capsule_id,replay_pass,semantic_match,provenance_review,sensitive_content_review,review_status\n"
        f"demo,{review_values},repository_review_pass\n",
        encoding="utf-8",
    )
    return capsule


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
            for path in (out, out.with_suffix(".csv"), out.with_suffix(".md")):
                self.assertNotIn(b"\r\n", path.read_bytes())
        finally:
            for path in (out, out.with_suffix(".csv"), out.with_suffix(".md")):
                if path.exists():
                    path.unlink()

    def test_audit_scans_orphan_json_credentials_and_common_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_auditable_capsule(root)
            (root / "auth.json").write_text('{"OPENAI_API_KEY": "sk-proj-abcdefghijklmnopqrstuvwxyz"}', encoding="utf-8")
            (root / ".env").write_text("NOTE=/workspace/student/project\n", encoding="utf-8")
            result = audit_directory(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("敏感凭据" in error for error in result["errors"]))
            self.assertTrue(any("绝对本机路径" in error for error in result["errors"]))

    def test_audit_detects_standard_auth_tokens_and_sorryax(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capsule = write_auditable_capsule(root)
            (root / "auth.json").write_text(
                '{"access_token": "abcdefghijklmnopqrstuvwxyz0123456789"}', encoding="utf-8"
            )
            manifest_path = capsule / "capsule.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["expected"] = {"compile_ok": True, "category": "ok", "diagnostic_key": "ok | success"}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (capsule / "Capsule.lean").write_text(
                "theorem unsafe : True := by exact sorryAx _ true\n", encoding="utf-8"
            )
            result = audit_directory(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("敏感凭据" in error for error in result["errors"]))
            self.assertTrue(any("占位符" in error for error in result["errors"]))

    def test_audit_requires_every_manual_review_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_auditable_capsule(root, review_values="false,false,false,false")
            result = audit_directory(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("复核字段未通过" in error for error in result["errors"]))

    def test_audit_rejects_compile_time_execution_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capsule = write_auditable_capsule(root)
            (capsule / "Capsule.lean").write_text('run_tac IO.println "unsafe"\n', encoding="utf-8")
            result = audit_directory(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("编译期执行入口" in error for error in result["errors"]))

    def test_audit_rejects_type_d_unsafe_inductive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capsule = write_auditable_capsule(root)
            unsafe_source = (
                ROOT / "benchmarks" / "security" / "unsafe_inductive_false.lean"
            ).read_text(encoding="utf-8")
            (capsule / "Capsule.lean").write_text(unsafe_source, encoding="utf-8")
            result = audit_directory(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("不安全声明" in error for error in result["errors"]))

    def test_audit_checks_environment_against_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            environment = {
                "lean_toolchain": "wrong",
                "lake_manifest_present": True,
                "lakefile_present": True,
                "local_files": ["missing.lean"],
                "dependency_project": None,
            }
            write_auditable_capsule(root, environment=environment)
            result = audit_directory(root)
            self.assertFalse(result["ok"])
            joined = "\n".join(result["errors"])
            self.assertIn("lean_toolchain 与文件不一致", joined)
            self.assertIn("lakefile_present 与文件不一致", joined)
            self.assertIn("lake_manifest_present 与文件不一致", joined)
            self.assertIn("local file 不存在", joined)

    def test_gallery_reports_malformed_manifest_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capsule = root / "bad"
            capsule.mkdir()
            (capsule / "capsule.json").write_text("{bad", encoding="utf-8")
            result = build_gallery_index(root)
            self.assertFalse(result["ok"])
            self.assertTrue(result["errors"])
