import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.export_pilot import COPY_FILES, reject_secrets, sanitize, validate_artifacts
from scripts.validate_pilot import validate_review, validate_runs


ROOT = Path(__file__).resolve().parents[1]


class ContinuousIntegrationTest(unittest.TestCase):
    def test_ci_runner_adds_repository_root_to_module_search_path(self):
        runner = (ROOT / "scripts" / "run_ci_tests.py").read_text(encoding="utf-8")
        self.assertIn("sys.path.insert(0, str(ROOT))", runner)

    def test_lean_is_installed_before_end_to_end_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("- name: Install Lean"), workflow.index("- name: Run tests"))

    def test_lean_project_is_built_before_end_to_end_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("- name: Build Lean project"), workflow.index("- name: Run tests"))

    def test_lean_action_only_installs_toolchain(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        install_block = workflow.split("- name: Install Lean", 1)[1].split(
            "- name: Install Python dependencies", 1
        )[0]
        self.assertIn("auto-config: false", install_block)
        self.assertIn("use-github-cache: false", install_block)

    def test_powershell_entrypoints_are_ascii_and_check_native_exit_codes(self):
        for relative in ("run_all.ps1", "scripts/setup_mathlib.ps1"):
            source = (ROOT / relative).read_bytes()
            self.assertTrue(source.isascii(), relative)
            text = source.decode("ascii")
            self.assertIn("$LASTEXITCODE", text, relative)
            self.assertIn("Invoke-NativeCommand", text, relative)

    def test_mathlib_setup_defines_a_stable_cache_directory(self):
        powershell = (ROOT / "scripts" / "setup_mathlib.ps1").read_text(encoding="ascii")
        shell = (ROOT / "scripts" / "setup_mathlib.sh").read_text(encoding="utf-8")
        self.assertIn("MATHLIB_CACHE_DIR", powershell)
        self.assertIn("MATHLIB_CACHE_DIR", shell)

    def test_formal_runner_requests_fresh_state_and_defaults_to_no_cache_reuse(self):
        runner = (ROOT / "run_all.ps1").read_text(encoding="ascii")
        self.assertIn('"--fresh"', runner)
        self.assertIn("[switch]$ReuseCache", runner)
        self.assertIn('"--allow-cache-hits"', runner)
        self.assertIn('"--allow-unreviewed"', runner)
        self.assertLess(runner.index('@("build")'), runner.index('"-m", "unittest"'))

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser is only available on Windows")
    def test_powershell_entrypoints_parse_with_windows_powershell(self):
        command = (
            "$failed = $false; "
            "foreach ($file in @('run_all.ps1','scripts/setup_mathlib.ps1')) { "
            "$tokens = $null; $errors = $null; "
            "[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $file), "
            "[ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; $failed = $true } }; "
            "if ($failed) { exit 1 }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ci_has_a_windows_powershell_static_job(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("windows-latest", workflow)
        self.assertIn("Parser]::ParseFile", workflow)

    def test_part2_workflow_contract(self):
        workflow = (ROOT / ".github" / "workflows" / "part2.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("- leiteng", workflow)
        self.assertIn("ubuntu-latest", workflow)
        self.assertIn("windows-latest", workflow)
        self.assertIn("tests.test_feedback", workflow)
        self.assertIn("python scripts/run_ci_tests.py", workflow)
        self.assertIn("run: lake build", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("secrets.", workflow)

    def test_pilot_validator_rejects_cache_hits_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            manifest = base / "manifest.json"
            runs = base / "runs.jsonl"
            manifest.write_text(json.dumps([{"id": "demo"}]), encoding="utf-8")
            rows = [
                {
                    "experiment_id": "pilot-demo",
                    "run_id": f"run-{condition}",
                    "condition": condition,
                    "problem_id": "demo",
                    "round": 1,
                    "compile_ok": True,
                    "cache_hit": condition == "B",
                    "provider_config": {"provider": "demo", "model": "fixed"},
                    "candidate_policy": {
                        "version": "tracer-candidate-v1",
                        "meta_execution": "blocked",
                        "environment": "minimal",
                    },
                    "provider_error": None,
                    "diagnostic": {"category": "ok"},
                }
                for condition in ("A", "B", "C")
            ]
            runs.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            command = [
                os.fspath(Path(sys.executable)),
                os.fspath(ROOT / "scripts" / "validate_pilot.py"),
                "--runs",
                os.fspath(runs),
                "--manifest",
                os.fspath(manifest),
            ]
            strict = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            allowed = subprocess.run(
                command + ["--allow-cache-hits"], cwd=ROOT, capture_output=True, text=True, check=False
            )
            self.assertEqual(strict.returncode, 1, strict.stdout + strict.stderr)
            self.assertIn("cache hit", strict.stdout)
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)

    def test_pilot_validator_rejects_mixed_runs_and_adverse_manual_review(self):
        expected = {(condition, "demo") for condition in ("A", "B", "C")}
        rows = [
            {
                "experiment_id": "exp",
                "run_id": f"run-{condition}",
                "condition": condition,
                "problem_id": "demo",
                "round": 1,
                "compile_ok": condition == "A",
                "cache_hit": False,
                "provider_config": {"provider": "demo"},
                "candidate_policy": {
                    "version": "tracer-candidate-v1",
                    "meta_execution": "blocked",
                    "environment": "minimal",
                },
                "provider_error": None,
                "diagnostic": {"category": "ok" if condition == "A" else "type_mismatch"},
            }
            for condition in ("A", "B", "C")
        ]
        rows[0]["compile_ok"] = False
        rows.insert(1, {**rows[0], "run_id": "different-run", "round": 2, "compile_ok": True})
        errors = validate_runs(rows, expected, allow_cache_hits=False)
        self.assertTrue(any("mixes run_id" in error for error in errors))

        with tempfile.TemporaryDirectory() as temp:
            review = Path(temp) / "review.csv"
            review.write_text(
                "experiment_id,problem_id,condition,kernel_pass,inappropriate_assumption,leakage_risk,reviewer_note\n"
                "exp,demo,A,yes,no,yes,checked\n"
                "exp,demo,B,,,,\n"
                "exp,demo,C,,,,\n",
                encoding="utf-8",
            )
            errors = validate_review(review, expected, rows)
        self.assertTrue(any("leakage risk" in error for error in errors))

    def test_handoff_export_sanitizes_paths_and_rejects_obvious_credentials(self):
        value = {"source_file": "C:/Users/demo/project/file.lean", "items": ["C:/Temp/run.lean"]}
        cleaned = sanitize(value, [("C:/Users/demo/project", "<repo>"), ("C:/Temp", "<temp>")])
        self.assertEqual(cleaned["source_file"], "<repo>/file.lean")
        self.assertEqual(cleaned["items"], ["<temp>/run.lean"])
        reject_secrets(cleaned)
        with self.assertRaisesRegex(ValueError, "possible credential"):
            reject_secrets({"authorization": "Bearer abcdefghijklmnop"})
        with self.assertRaisesRegex(ValueError, "possible credential"):
            reject_secrets({"access_token": "abcdefghijklmnopqrstuvwxyz0123456789"})

    def test_handoff_requires_matching_formal_report_and_success_proofs(self):
        rows = [{
            "experiment_id": "exp-1",
            "condition": "A",
            "problem_id": "demo",
            "compile_ok": True,
            "source_file": "C:/work/Demo.lean",
            "theorem": "Demo.target",
        }]
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report_path = base / "REPORT.md"
            errors = validate_artifacts(rows, results=base, report_path=report_path)
            self.assertTrue(any("missing report artifact" in error for error in errors))

            report_path.write_text("# formal\n", encoding="utf-8")
            for name in COPY_FILES:
                path = base / name
                if name == "pilot_report.json":
                    path.write_text(
                        json.dumps({
                            "status": "formal",
                            "experiment_id": "exp-1",
                            "candidate_policy": {
                                "version": "tracer-candidate-v1",
                                "meta_execution": "blocked",
                                "environment": "minimal",
                            },
                        }),
                        encoding="utf-8",
                    )
                else:
                    path.write_text("artifact\n", encoding="utf-8")
            proof = base / "solutions" / "A" / "Demo__Demo.target.lean"
            proof.parent.mkdir(parents=True)
            proof.write_text("theorem target : True := by trivial\n", encoding="utf-8")
            self.assertEqual(validate_artifacts(rows, results=base, report_path=report_path), [])

            (base / "pilot_report.json").write_text(
                json.dumps({
                    "status": "draft",
                    "experiment_id": "exp-1",
                    "candidate_policy": {
                        "version": "tracer-candidate-v1",
                        "meta_execution": "blocked",
                        "environment": "minimal",
                    },
                }),
                encoding="utf-8",
            )
            errors = validate_artifacts(rows, results=base, report_path=report_path)
            self.assertTrue(any("not a formal report" in error for error in errors))
