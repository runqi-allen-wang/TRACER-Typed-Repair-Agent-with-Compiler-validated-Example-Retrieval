"""用离线命令替身验证安装脚本，避免测试依赖外网或真实下载。"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASH = (
    str(Path("C:/Program Files/Git/bin/bash.exe"))
    if os.name == "nt" and Path("C:/Program Files/Git/bin/bash.exe").exists()
    else shutil.which("bash")
)

# 保留真实目录移动行为，只替换 Lake、Git 检查和等待。
HARNESS = r"""
lake() {
  local phase count_file count failed
  if [[ "$*" == "update" ]]; then
    phase=update
    failed="$FAKE_UPDATE_FAILURES"
  elif [[ "$*" == "exe cache get" ]]; then
    phase=cache
    failed="$FAKE_CACHE_FAILURES"
  else
    return 91
  fi
  count_file="$PWD/$phase.count"
  count=0
  if [[ -f "$count_file" ]]; then read -r count < "$count_file"; fi
  count=$((count + 1))
  printf '%s\n' "$count" > "$count_file"
  printf '%s\n' "$MATHLIB_CACHE_DIR" > "$PWD/cache-env.txt"
  if ((count <= failed)); then
    if [[ "$phase" == update && "$FAKE_PARTIAL_CLONE" == 1 ]]; then
      mkdir -p "$PWD/.lake/packages/LeanSearchClient/.git"
      printf 'partial clone\n' > "$PWD/.lake/packages/LeanSearchClient/interrupted.txt"
    fi
    echo "SSL connection timeout" >&2
    return "$FAKE_EXIT_CODE"
  fi
  return 0
}
git() {
  if [[ "$1" != -C || "$3" != rev-parse || "$4" != --verify || "$5" != 'HEAD^{commit}' ]]; then
    return 92
  fi
  [[ -f "$2/.git/valid-head" ]]
}
sleep() {
  printf '%s\n' "$1" >> "$PWD/sleep.log"
}
source "$1" "$2"
"""


@unittest.skipUnless(BASH, "安装脚本回归测试需要 Bash")
class MathlibSetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tracer setup ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "project with spaces"
        self.project.mkdir()
        self.harness = self.base / "harness.sh"
        self.harness.write_text(HARNESS, encoding="utf-8", newline="\n")

    def run_setup(self, **overrides):
        env = os.environ.copy()
        for key in ("MATHLIB_CACHE_DIR", "TRACER_SETUP_ATTEMPTS", "TRACER_SETUP_RETRY_DELAY"):
            env.pop(key, None)
        env.update(
            TRACER_SETUP_ATTEMPTS="3", TRACER_SETUP_RETRY_DELAY="5",
            FAKE_UPDATE_FAILURES="0", FAKE_CACHE_FAILURES="0",
            FAKE_PARTIAL_CLONE="0", FAKE_EXIT_CODE="1",
        )
        env.update({key: str(value) for key, value in overrides.items()})
        return subprocess.run(
            [BASH, self.harness.as_posix(), (ROOT / "scripts/setup_mathlib.sh").as_posix(),
             self.project.as_posix()],
            cwd=self.base, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )

    def count(self, phase):
        path = self.project / f"{phase}.count"
        return int(path.read_text(encoding="utf-8")) if path.exists() else 0

    def make_package(self, name, valid=False):
        package = self.project / ".lake/packages" / name
        (package / ".git").mkdir(parents=True)
        if valid:
            (package / ".git/valid-head").touch()
        return package

    def test_success_from_another_directory_with_spaces(self):
        result = self.run_setup()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual((1, 1), (self.count("update"), self.count("cache")))
        self.assertTrue((self.project / ".lake/mathlib-cache").is_dir())
        self.assertFalse((self.project / "sleep.log").exists())

    def test_transient_update_failure_uses_bounded_backoff(self):
        result = self.run_setup(FAKE_UPDATE_FAILURES=2)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual((3, 1), (self.count("update"), self.count("cache")))
        self.assertEqual(["5", "10"], (self.project / "sleep.log").read_text().splitlines())

    def test_exhausted_update_keeps_failure_and_does_not_download_cache(self):
        result = self.run_setup(FAKE_UPDATE_FAILURES=9, FAKE_EXIT_CODE=23)
        self.assertEqual(23, result.returncode)
        self.assertEqual((3, 0), (self.count("update"), self.count("cache")))
        self.assertIn("SSL connection timeout", result.stderr)
        self.assertNotIn("Mathlib 环境准备完成", result.stdout)

    def test_cache_download_is_retried(self):
        result = self.run_setup(FAKE_CACHE_FAILURES=2)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual((1, 3), (self.count("update"), self.count("cache")))

    def test_exhausted_cache_failure_is_not_hidden(self):
        result = self.run_setup(FAKE_CACHE_FAILURES=9, FAKE_EXIT_CODE=17)
        self.assertEqual(17, result.returncode)
        self.assertEqual((1, 3), (self.count("update"), self.count("cache")))
        self.assertNotIn("Mathlib 环境准备完成", result.stdout)

    def test_interrupted_transitive_clone_is_backed_up_before_retry(self):
        valid = self.make_package("mathlib", valid=True)
        local = self.project / ".lake/packages/local-dependency"
        local.mkdir()
        result = self.run_setup(FAKE_UPDATE_FAILURES=1, FAKE_PARTIAL_CLONE=1)
        self.assertEqual(0, result.returncode, result.stderr)
        backups = list((self.project / ".lake/retry-backups").glob("*/LeanSearchClient/interrupted.txt"))
        self.assertEqual(1, len(backups))
        self.assertEqual("partial clone\n", backups[0].read_text())
        self.assertFalse((self.project / ".lake/packages/LeanSearchClient").exists())
        self.assertTrue((valid / ".git/valid-head").exists())
        self.assertTrue(local.is_dir())

    def test_preexisting_incomplete_clone_is_backed_up(self):
        broken = self.make_package("plausible")
        (broken / "keep.txt").write_text("recoverable", encoding="utf-8")
        result = self.run_setup()
        self.assertEqual(0, result.returncode, result.stderr)
        backups = list((self.project / ".lake/retry-backups").glob("*/plausible/keep.txt"))
        self.assertEqual(1, len(backups))
        self.assertEqual("recoverable", backups[0].read_text())

    def test_valid_precompiled_cache_skips_download(self):
        package = self.make_package("mathlib", valid=True)
        probe = package / ".lake/build/lib/lean/Mathlib.olean"
        probe.parent.mkdir(parents=True)
        probe.touch()
        result = self.run_setup()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual((1, 0), (self.count("update"), self.count("cache")))

    def test_explicit_cache_directory_is_respected(self):
        cache = self.base / "custom cache"
        result = self.run_setup(MATHLIB_CACHE_DIR=cache.as_posix())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(cache.is_dir())
        self.assertEqual(cache.as_posix(), (self.project / "cache-env.txt").read_text().strip())

    def test_invalid_retry_options_fail_before_lake(self):
        for options in (
            {"TRACER_SETUP_ATTEMPTS": "0"},
            {"TRACER_SETUP_ATTEMPTS": "99"},
            {"TRACER_SETUP_RETRY_DELAY": "-1"},
            {"TRACER_SETUP_RETRY_DELAY": "31"},
        ):
            with self.subTest(options=options):
                result = self.run_setup(**options)
                self.assertEqual(2, result.returncode)
                self.assertEqual(0, self.count("update"))

    @unittest.skipIf(os.name == "nt", "符号链接边界在 Linux CI 验证")
    def test_symlinked_managed_directory_is_not_moved(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("do not touch", encoding="utf-8")
        (self.project / ".lake").symlink_to(outside, target_is_directory=True)
        result = self.run_setup()
        self.assertEqual(2, result.returncode)
        self.assertEqual("do not touch", (outside / "keep.txt").read_text())
        self.assertEqual(0, self.count("update"))

    @unittest.skipIf(os.name == "nt", "符号链接边界在 Linux CI 验证")
    def test_symlinked_package_is_not_moved(self):
        outside = self.base / "outside"
        (outside / ".git").mkdir(parents=True)
        packages = self.project / ".lake/packages"
        packages.mkdir(parents=True)
        (packages / "linked-package").symlink_to(outside, target_is_directory=True)
        result = self.run_setup()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((packages / "linked-package").is_symlink())
        self.assertTrue((outside / ".git").is_dir())
        self.assertFalse((self.project / ".lake/retry-backups").exists())


if __name__ == "__main__":
    unittest.main()
