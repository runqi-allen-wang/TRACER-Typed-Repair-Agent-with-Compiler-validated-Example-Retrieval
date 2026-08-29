import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compiler import FileCompileResult
from leancapsule.diagnostics_key import diagnostic_key
from leancapsule.extract import extract_theorem
from leancapsule.minimize import minimize_imports
from leancapsule.pack import pack_capsule
from leancapsule.replay import replay_capsule
from leancapsule.schema import validate_json_schema, validate_manifest


class CapsuleTest(unittest.TestCase):
    def test_diagnostic_key_is_readable_and_path_independent(self):
        left = diagnostic_key({"category": "type_mismatch", "summary": "C:\\tmp\\a.lean:2:4: bad type"})
        right = diagnostic_key({"category": "type_mismatch", "summary": "/var/tmp/b.lean:20:8: bad type"})
        self.assertEqual(left, right)

    def test_success_key_ignores_download_info(self):
        self.assertEqual(
            diagnostic_key({"category": "ok", "summary": "info: downloading http<local-path>"}),
            "ok | Lean 编译通过。",
        )

    def test_both_module_entrypoints_are_usable(self):
        for module in ("leancapsule", "src.leancapsule"):
            completed = subprocess.run(
                [sys.executable, "-m", module, "--help"],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import leancapsule.pack; import leancapsule; assert leancapsule.diagnostic_key",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_manifest_schema_validation(self):
        manifest = {
            "schema_version": "leancapsule.v0.1",
            "capsule_id": "demo",
            "target": {"source_file": "Demo.lean", "selection_mode": "lines", "lines": "1:1"},
            "environment": {},
            "expected": {"compile_ok": False, "category": "compile_error", "diagnostic_key": "compile_error | x"},
            "provenance": {"license": "MIT", "source_url": None, "notes": "测试 manifest"},
            "replay": {"file": "Capsule.lean", "command": "python -m leancapsule replay ."},
        }
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(validate_json_schema(manifest), [])

    def test_standalone_extraction_keeps_import_and_namespace(self):
        source = "import Std\nnamespace Demo\ndef helper : Nat := 1\ntheorem target : True := by trivial\nend Demo\n"
        extracted = extract_theorem(source, "Demo.target")
        self.assertIn("import Std", extracted)
        self.assertIn("namespace Demo", extracted)
        self.assertIn("theorem target", extracted)
        self.assertNotIn("def helper", extracted)

    def test_import_minimization_accepts_only_matching_key(self):
        source = "import Std\nimport Init\n\ntheorem target : True := by trivial\n"
        calls = []

        def trial(candidate):
            calls.append(candidate)
            return True, "ok | same"

        minimized, info = minimize_imports(source, trial, "ok | same")
        self.assertEqual(info["removed_imports"], 2)
        self.assertNotIn("import Std", minimized)
        self.assertEqual(len(calls), 2)

    def test_pack_writes_replayable_files_without_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "Demo.lean"
            source.write_text("import Std\nexample : True := by exact True.intro\n", encoding="utf-8")
            fake = FileCompileResult(True, 1.0, "", False, 0, ["lean", str(source)])
            with patch("leancapsule.pack.run_lean_file", return_value=fake):
                manifest = pack_capsule(base, source, base / "capsule", lines="1:2")
            self.assertEqual(manifest["expected"]["category"], "ok")
            self.assertTrue((base / "capsule" / "capsule.json").exists())
            replay_ps1 = base / "capsule" / "replay.ps1"
            self.assertTrue(replay_ps1.read_bytes().startswith(bytes([239, 187, 191])))
            self.assertIn("$CapsuleRoot", replay_ps1.read_text(encoding="utf-8-sig"))
            self.assertIn("REPOSITORY_ROOT", (base / "capsule" / "replay.sh").read_text(encoding="utf-8"))
            text = (base / "capsule" / "capsule.json").read_text(encoding="utf-8")
            self.assertNotIn("secret", text.lower())
            diagnostic = (base / "capsule" / "expected-diagnostic.txt").read_text(encoding="utf-8")
            self.assertNotIn(str(base), diagnostic)

    def test_replay_matches_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            capsule = base / "capsule"
            capsule.mkdir()
            manifest = {
                "schema_version": "leancapsule.v0.1",
                "capsule_id": "demo",
                "target": {"source_file": "Demo.lean", "selection_mode": "lines", "lines": "1:1"},
                "environment": {},
                "expected": {"compile_ok": False, "returncode": 1, "category": "unknown_identifier", "diagnostic_key": "unknown_identifier | unknown_identifier: Unknown identifier `missing`"},
                "provenance": {"license": "MIT"},
                "replay": {"file": "Capsule.lean"},
            }
            (capsule / "capsule.json").write_text(json.dumps(manifest), encoding="utf-8")
            (capsule / "Capsule.lean").write_text("", encoding="utf-8")
            fake = FileCompileResult(False, 1.0, "x:1:1: error: Unknown identifier `missing`", False, 1, ["lean", "Capsule.lean"])
            with patch("leancapsule.replay.run_lean_file", return_value=fake):
                result = replay_capsule(capsule)
            self.assertTrue(result["ok"])

    def test_pack_and_replay_reject_type_d_before_compilation(self):
        unsafe_source = (ROOT / "benchmarks" / "security" / "unsafe_inductive_false.lean").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "Unsafe.lean"
            source.write_text(unsafe_source, encoding="utf-8")
            with patch("leancapsule.pack.run_lean_file") as compile_mock:
                with self.assertRaisesRegex(ValueError, "不安全声明|编译期执行入口"):
                    pack_capsule(base, source, base / "capsule", lines="1:1")
            compile_mock.assert_not_called()

            capsule = base / "replay-capsule"
            capsule.mkdir()
            manifest = {
                "schema_version": "leancapsule.v0.1",
                "capsule_id": "unsafe-demo",
                "target": {"source_file": "Unsafe.lean", "selection_mode": "lines", "lines": "1:1"},
                "environment": {},
                "expected": {"compile_ok": False, "category": "compile_error", "diagnostic_key": "x"},
                "provenance": {"license": "MIT"},
                "replay": {"file": "Capsule.lean"},
            }
            (capsule / "capsule.json").write_text(json.dumps(manifest), encoding="utf-8")
            (capsule / "Capsule.lean").write_text(unsafe_source, encoding="utf-8")
            with patch("leancapsule.replay.run_lean_file") as compile_mock:
                result = replay_capsule(capsule)
            compile_mock.assert_not_called()
            self.assertFalse(result["ok"])
            self.assertRegex(result["error"], "不安全声明|编译期执行入口")
