import json
import os
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
from leancapsule.pack import _write_scripts, pack_capsule
from leancapsule.replay import _redact_text, replay_capsule
from leancapsule.schema import validate_full_manifest, validate_json_schema, validate_manifest
from leancapsule.verify import verify_directory


def valid_manifest(*, compile_ok=False, category="compile_error", diagnostic_key="compile_error | x", replay_file="Capsule.lean", dependency_project=None):
    return {
        "schema_version": "leancapsule.v0.1",
        "capsule_id": "capsule",
        "target": {"source_file": "Demo.lean", "selection_mode": "lines", "lines": "1:1"},
        "environment": {"dependency_project": dependency_project},
        "expected": {"compile_ok": compile_ok, "returncode": 0 if compile_ok else 1, "category": category, "diagnostic_key": diagnostic_key},
        "provenance": {"license": "MIT", "source_url": None, "notes": "test"},
        "replay": {"file": replay_file, "command": "python -m leancapsule replay ."},
    }


class CapsuleTest(unittest.TestCase):
    def test_diagnostic_key_is_readable_and_path_independent(self):
        left = diagnostic_key({"category": "type_mismatch", "summary": "C:\\tmp\\a.lean:2:4: bad type"})
        right = diagnostic_key({"category": "type_mismatch", "summary": "/var/tmp/b.lean:20:8: bad type"})
        self.assertEqual(left, right)

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
        self.assertEqual(validate_full_manifest(manifest), [])

        incomplete = dict(manifest)
        incomplete["replay"] = {"file": "Capsule.lean"}
        self.assertTrue(validate_full_manifest(incomplete))

    def test_standalone_extraction_keeps_import_and_namespace(self):
        source = "import Std\nnamespace Demo\ndef helper : Nat := 1\ntheorem target : True := by trivial\nend Demo\n"
        extracted = extract_theorem(source, "Demo.target")
        self.assertIn("import Std", extracted)
        self.assertIn("namespace Demo", extracted)
        self.assertIn("theorem target", extracted)
        self.assertNotIn("def helper", extracted)

    def test_standalone_extraction_ignores_closed_and_preserves_nested_namespaces(self):
        closed = "namespace Closed\nend Closed\n\ntheorem target : True := by trivial\n\ndef unrelated : Nat := 1\n"
        extracted = extract_theorem(closed, "target")
        self.assertNotIn("namespace Closed", extracted)
        self.assertNotIn("def unrelated", extracted)

        nested = "namespace A\nsection S\nnamespace B\ntheorem target : True := by trivial\nend B\nend S\nend A\n"
        extracted = extract_theorem(nested, "A.B.target")
        self.assertIn("namespace A\nnamespace B", extracted)
        self.assertTrue(extracted.rstrip().endswith("end B\nend A"))

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
            def inspect_staging(capsule, timeout):
                for name in ("Capsule.lean", "capsule.json", "expected-diagnostic.txt", "README.md", "replay.ps1", "replay.sh"):
                    self.assertTrue((capsule / name).is_file(), name)
                return {"ok": True}

            with patch("leancapsule.pack.run_lean_file", return_value=fake), patch("leancapsule.pack.replay_capsule", side_effect=inspect_staging) as replay:
                manifest = pack_capsule(base, source, base / "capsule", lines="1:2")
            replay.assert_called_once()
            self.assertEqual(manifest["expected"]["category"], "ok")
            self.assertTrue((base / "capsule" / "capsule.json").exists())
            self.assertIn("$PSScriptRoot", (base / "capsule" / "replay.ps1").read_text(encoding="utf-8"))
            self.assertIn('dirname -- "$0"', (base / "capsule" / "replay.sh").read_text(encoding="utf-8"))
            self.assertNotIn(b"\r\n", (base / "capsule" / "replay.sh").read_bytes())
            text = (base / "capsule" / "capsule.json").read_text(encoding="utf-8")
            self.assertNotIn("secret", text.lower())
            diagnostic = (base / "capsule" / "expected-diagnostic.txt").read_text(encoding="utf-8")
            self.assertNotIn(str(base), diagnostic)

    def test_pack_rejects_nonempty_output_and_cleans_failed_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "Demo.lean"
            source.write_text("example : True := by trivial\n", encoding="utf-8")
            out = base / "capsule"
            out.mkdir()
            (out / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                pack_capsule(base, source, out, lines="1:1")
            self.assertEqual((out / "keep.txt").read_text(encoding="utf-8"), "keep")

            out = base / "new-capsule"
            fake = FileCompileResult(True, 1.0, "", False, 0, ["lean", str(source)])
            with patch("leancapsule.pack.run_lean_file", return_value=fake), patch("leancapsule.pack.replay_capsule", return_value={"ok": False, "error": "mismatch"}):
                with self.assertRaisesRegex(RuntimeError, "回放验证失败"):
                    pack_capsule(base, source, out, lines="1:1")
            self.assertFalse(out.exists())
            self.assertEqual(list(base.glob(".new-capsule-*")), [])

    def test_pack_and_replay_reject_compile_time_execution_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "Unsafe.lean"
            unsafe_inductive = (ROOT / "benchmarks" / "security" / "unsafe_inductive_false.lean").read_text(
                encoding="utf-8"
            )
            for name, unsafe_source in {
                "run-tac": 'run_tac IO.println "unsafe"\n',
                "type-d-unsafe-inductive": unsafe_inductive,
            }.items():
                with self.subTest(name=name):
                    source.write_text(unsafe_source, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "不安全声明|编译期执行入口"):
                        pack_capsule(base, source, base / f"capsule-{name}", lines="1:1")

            capsule = base / "replay-capsule"
            capsule.mkdir()
            manifest = valid_manifest()
            (capsule / "capsule.json").write_text(json.dumps(manifest), encoding="utf-8")
            (capsule / "Capsule.lean").write_text(unsafe_inductive, encoding="utf-8")
            result = replay_capsule(capsule)
            self.assertFalse(result["ok"])
            self.assertRegex(result["error"], "不安全声明|编译期执行入口")

    def test_pack_rejects_timeout_and_records_lakefile_lean(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "Demo.lean"
            source.write_text("example : True := by trivial\n", encoding="utf-8")
            timeout_result = FileCompileResult(False, 1.0, "timeout", True, None, ["lean", str(source)])
            with patch("leancapsule.pack.run_lean_file", return_value=timeout_result):
                with self.assertRaisesRegex(RuntimeError, "编译超时"):
                    pack_capsule(base, source, base / "timed-out", lines="1:1")
            self.assertFalse((base / "timed-out").exists())

            (base / "lakefile.lean").write_text("import Lake\n", encoding="utf-8")
            fake = FileCompileResult(True, 1.0, "", False, 0, ["lean", str(source)])
            with patch("leancapsule.pack.run_lean_file", return_value=fake), patch("leancapsule.pack.replay_capsule", return_value={"ok": True}):
                manifest = pack_capsule(base, source, base / "lake-capsule", lines="1:1")
            self.assertTrue(manifest["environment"]["lakefile_present"])

    def test_replay_matches_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            capsule = base / "capsule"
            capsule.mkdir()
            manifest = valid_manifest(category="unknown_identifier", diagnostic_key="unknown_identifier | unknown_identifier: Unknown identifier `missing`")
            (capsule / "capsule.json").write_text(json.dumps(manifest), encoding="utf-8")
            (capsule / "Capsule.lean").write_text("", encoding="utf-8")
            fake = FileCompileResult(False, 1.0, "x:1:1: error: Unknown identifier `missing`", False, 1, ["lean", "Capsule.lean"])
            with patch("leancapsule.replay.run_lean_file", return_value=fake):
                result = replay_capsule(capsule)
            self.assertTrue(result["ok"])

    def test_replay_rejects_schema_errors_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            capsule = base / "capsule"
            capsule.mkdir()
            (capsule / "Capsule.lean").write_text("", encoding="utf-8")
            incomplete = valid_manifest()
            incomplete["replay"] = {"file": "Capsule.lean"}
            (capsule / "capsule.json").write_text(json.dumps(incomplete), encoding="utf-8")
            self.assertFalse(replay_capsule(capsule)["ok"])

            escaped = valid_manifest(replay_file="../outside.lean")
            (base / "outside.lean").write_text("", encoding="utf-8")
            (capsule / "capsule.json").write_text(json.dumps(escaped), encoding="utf-8")
            with patch("leancapsule.replay.run_lean_file") as compiler:
                result = replay_capsule(capsule)
            self.assertFalse(result["ok"])
            self.assertIn("不能逃逸", result["error"])
            compiler.assert_not_called()

            escaped = valid_manifest(dependency_project="..")
            (capsule / "capsule.json").write_text(json.dumps(escaped), encoding="utf-8")
            result = replay_capsule(capsule)
            self.assertFalse(result["ok"])
            self.assertIn("不能逃逸", result["error"])

    def test_replay_redacts_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            capsule = Path(temp) / "capsule"
            capsule.mkdir()
            source = capsule / "Capsule.lean"
            source.write_text("", encoding="utf-8")
            manifest = valid_manifest(compile_ok=False, category="type_mismatch", diagnostic_key="type_mismatch | type_mismatch: Type mismatch")
            (capsule / "capsule.json").write_text(json.dumps(manifest), encoding="utf-8")
            diagnostics = f"{source}:1:1: error: Type mismatch"
            fake = FileCompileResult(False, 1.0, diagnostics, False, 1, ["lean", str(source)])
            with patch("leancapsule.replay.run_lean_file", return_value=fake):
                result = replay_capsule(capsule)
            public = json.dumps(result, ensure_ascii=False)
            self.assertTrue(result["ok"])
            self.assertNotIn(str(capsule), public)
            self.assertIn("<capsule>", public)

    def test_replay_redacts_unrelated_home_and_temp_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            capsule = Path(temp) / "capsule"
            capsule.mkdir()
            source = capsule / "Capsule.lean"
            home_file = Path.home() / "private" / "credentials.json"
            temp_file = Path(tempfile.gettempdir()) / "unrelated" / "trace.log"
            cleaned = _redact_text(
                f"home={home_file}; temp={temp_file}", capsule, source, capsule
            )
            self.assertNotIn(str(Path.home()), cleaned)
            self.assertNotIn(str(Path(tempfile.gettempdir())), cleaned)
            self.assertIn("<home>", cleaned)

    def test_verify_rejects_empty_and_preserves_bad_manifest_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertFalse(verify_directory(root)["ok"])
            bad = root / "bad"
            bad.mkdir()
            (bad / "capsule.json").write_text("{bad", encoding="utf-8")
            result = verify_directory(root)
            self.assertFalse(result["ok"])
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertIn("manifest 无法读取", result["results"][0]["error"])

    def test_replay_scripts_use_their_own_directory_from_two_working_directories(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as temp:
            base = Path(temp)
            capsule = base / "capsule"
            capsule.mkdir()
            _write_scripts(capsule)
            bin_dir = base / "bin"
            bin_dir.mkdir()
            log = base / "calls.txt"
            env = os.environ.copy()
            env["CAPSULE_SCRIPT_LOG"] = str(log)
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            if os.name == "nt":
                shim = bin_dir / "python.cmd"
                shim.write_text('@echo %CD%^|%*>>"%CAPSULE_SCRIPT_LOG%"\r\n@exit /b 0\r\n', encoding="utf-8")
                command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(capsule / "replay.ps1")]
            else:
                shim = bin_dir / "python"
                shim.write_text('#!/bin/sh\nprintf "%s|%s\\n" "$PWD" "$*" >> "$CAPSULE_SCRIPT_LOG"\n', encoding="utf-8")
                shim.chmod(0o755)
                command = ["sh", str(capsule / "replay.sh")]
            for cwd in (ROOT, capsule):
                completed = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
            calls = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(line.startswith(str(ROOT.resolve())) for line in calls))
            self.assertTrue(all(str(capsule.resolve()) in line for line in calls))

    def test_both_module_entrypoints_are_usable(self):
        for module in ("leancapsule", "src.leancapsule"):
            completed = subprocess.run([sys.executable, "-m", module, "--help"], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
        completed = subprocess.run([sys.executable, "-c", "import leancapsule.pack; import leancapsule; assert leancapsule.diagnostic_key"], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
