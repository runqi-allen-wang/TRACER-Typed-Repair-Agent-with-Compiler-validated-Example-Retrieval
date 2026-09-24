import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from security_isolation import (  # noqa: E402
    IsolationError,
    PROTOCOL_VERSION,
    build_container_command,
    check_report,
    load_profile,
    plan,
    run_probe,
    runtime_environment,
    validate_probe,
)
from audit_security_isolation_release import audit_release  # noqa: E402


class SecurityIsolationTest(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(ROOT)

    def passing_probe(self) -> dict:
        checks = {name: True for name in self.profile["required_controls"]}
        return {
            "profile_version": self.profile["version"],
            "checks": checks,
            "evidence": {},
            "all_required_controls_passed": True,
        }

    def test_profile_freezes_low_privilege_boundaries(self):
        planned = plan(ROOT)
        self.assertEqual(planned["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(planned["runtime"], "docker")
        self.assertEqual(planned["container_user"], "65532:65532")
        self.assertEqual(planned["dangerous_lean_execution"], "forbidden")
        self.assertEqual(planned["network_calls"], 0)
        self.assertGreaterEqual(len(planned["required_controls"]), 14)

    def test_container_command_is_fail_closed(self):
        command = build_container_command(ROOT, "docker", self.profile["image"], self.profile)
        joined = " ".join(command)
        self.assertIn("--read-only", command)
        self.assertIn("--network none", joined)
        self.assertIn("--cap-drop ALL", joined)
        self.assertIn("--security-opt no-new-privileges:true", joined)
        self.assertIn("--user 65532:65532", joined)
        self.assertIn("/tmp:rw,noexec,nosuid,nodev", joined)
        self.assertIn("dst=/workspace,readonly", joined)
        self.assertNotIn("--privileged", command)
        self.assertNotIn("/var/run/docker.sock", joined)
        self.assertIn("--entrypoint python", joined)
        self.assertEqual(command[-1], "/workspace/scripts/sp_isolation_probe.py")

    def test_runtime_environment_drops_credentials_and_proxies(self):
        hostile = {
            "PATH": "runtime-path",
            "LEAN_PROOF_API_KEY": "secret",
            "OPENAI_API_KEY": "secret",
            "HTTPS_PROXY": "http://user:password@example.invalid",
            "UNRELATED_TOKEN": "secret",
        }
        with patch.dict(os.environ, hostile, clear=True):
            environment = runtime_environment()
        self.assertEqual(environment["PATH"], "runtime-path")
        self.assertNotIn("LEAN_PROOF_API_KEY", environment)
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("HTTPS_PROXY", environment)
        self.assertNotIn("UNRELATED_TOKEN", environment)
        self.assertEqual(
            environment["TRACER_SP_SECRET_CANARY"],
            "TRACER_SP_CANARY_NOT_A_SECRET",
        )

    def test_probe_validation_fails_for_each_missing_control(self):
        for name in self.profile["required_controls"]:
            with self.subTest(control=name):
                probe = self.passing_probe()
                probe["checks"][name] = False
                errors = validate_probe(self.profile, probe)
                self.assertTrue(any(name in error for error in errors))

    def test_report_check_requires_observed_runtime_evidence(self):
        report = {
            "protocol_version": PROTOCOL_VERSION,
            "profile_version": self.profile["version"],
            "dangerous_lean_executed": False,
            "probe": self.passing_probe(),
            "errors": [],
            "ok": True,
        }
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            result = check_report(ROOT, report_path)
            self.assertTrue(result["ok"], result["errors"])
            report["probe"]["checks"]["network_egress_denied"] = False
            report_path.write_text(json.dumps(report), encoding="utf-8")
            failed = check_report(ROOT, report_path)
        self.assertFalse(failed["ok"])

    def test_run_refuses_to_claim_success_without_docker(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "security_isolation.shutil.which", return_value=None
        ):
            with self.assertRaisesRegex(IsolationError, "未找到 Docker"):
                run_probe(ROOT, Path(temp) / "output", False)

    def test_probe_never_loads_dangerous_lean_fixtures(self):
        source = (ROOT / "scripts/sp_isolation_probe.py").read_text(encoding="utf-8")
        self.assertNotIn("benchmarks/security/manifest.json", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("compile_candidate", source)

    def test_manual_workflow_does_not_run_on_push(self):
        workflow = (ROOT / ".github/workflows/sp-isolation.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("security_isolation.py run", workflow)
        self.assertIn("security_isolation.py check", workflow)

    def test_published_linux_evidence_is_audited_without_overclaiming(self):
        release = ROOT / "published" / "security-isolation-tracer-sp-v1"
        metadata = json.loads((release / "release.json").read_text(encoding="utf-8"))
        linux = metadata["platforms"]["linux_github_actions"]
        windows = metadata["platforms"]["windows_docker_desktop"]

        self.assertEqual(metadata["evidence_status"], "single_platform_observed")
        self.assertEqual(linux["status"], "observed_pass")
        self.assertEqual(linux["required_controls"], 14)
        self.assertEqual(linux["passed_controls"], 14)
        self.assertEqual(windows, {"status": "pending", "report": None})

        report = json.loads(
            (release / linux["report"]).read_text(encoding="utf-8")
        )
        self.assertFalse(report["dangerous_lean_executed"])
        self.assertTrue(all(report["probe"]["checks"].values()))

        audited = audit_release(release)
        self.assertTrue(audited["ok"], audited["errors"])
        self.assertEqual(audited["passed_controls"], 14)
        self.assertEqual(audited["observed_platforms"], 1)
        self.assertEqual(audited["pending_platforms"], 1)


if __name__ == "__main__":
    unittest.main()
