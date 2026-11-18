"""Local-only negative provenance tests; no HA installation or network calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "linux", "The canonical HA runner requires Linux")
class HarnessProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="controlel-ci-harness-")
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir()
        scripts = self.root / "scripts/agent"
        scripts.mkdir(parents=True)
        for name in ("ha-test.sh", "prepare-ha-environment.sh"):
            shutil.copyfile(ROOT / "scripts/agent" / name, scripts / name)
        (self.root / "requirements").mkdir()
        (self.root / "requirements/ha-test.txt").write_text("test lock\n")
        self.environment = Path(self.temporary.name) / "environment"
        (self.environment / "bin").mkdir(parents=True)
        (self.environment / "bin/python").symlink_to(sys.executable)
        self.git("init", "--initial-branch=task/ci-test")
        self.git("add", ".")
        self.git("-c", "user.name=CI local test", "-c", "user.email=ci-test@localhost", "commit", "-m", "local-only")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(self.root), *arguments], check=True, capture_output=True, text=True)

    def invoke(
        self, script: str, *, profile: str = "public", validate: bool = False
    ) -> subprocess.CompletedProcess[str]:
        command = [
            "bash",
            str(self.root / "scripts/agent" / script),
            "--worktree",
            str(self.root),
            "--baseline",
            self.sha,
            "--profile",
            profile,
            "--environment",
            str(self.environment),
        ]
        if validate:
            command.append("--validate")
        return subprocess.run(
            command, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        )

    def test_native_linux_public_fingerprint_and_no_overwrite(self) -> None:
        self.assertEqual(self.invoke("prepare-ha-environment.sh").returncode, 0)
        self.assertEqual(self.invoke("ha-test.sh", validate=True).returncode, 0)
        self.assertNotEqual(self.invoke("prepare-ha-environment.sh").returncode, 0)
        self.assertNotEqual(self.invoke("ha-test.sh", profile="checked-out-wheel", validate=True).returncode, 0)

    def test_missing_changed_lock_and_foreign_worktree_fail_closed(self) -> None:
        self.assertNotEqual(self.invoke("ha-test.sh", validate=True).returncode, 0)
        self.assertEqual(self.invoke("prepare-ha-environment.sh").returncode, 0)
        lock = self.root / "requirements/ha-test.txt"
        lock.write_text("changed lock\n")
        self.assertNotEqual(self.invoke("ha-test.sh", validate=True).returncode, 0)
        lock.write_text("test lock\n")
        fingerprint = self.environment / ".controlel-harness-v2.json"
        data = json.loads(fingerprint.read_text())
        data["worktree"] = "/tmp/foreign-checkout"
        fingerprint.write_text(json.dumps(data))
        self.assertNotEqual(self.invoke("ha-test.sh", validate=True).returncode, 0)

    def test_ci_guard_rejects_wrong_sha_event_and_profile(self) -> None:
        for overrides in (
            {"CI_COMMIT_SHA": "0" * 40},
            {"CI_COMMIT_SHA": "short"},
            {"CI_PIPELINE_EVENT": "unapproved"},
            {"TEST_PROFILE": "pretend-pass"},
        ):
            with self.subTest(overrides=overrides):
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts/ci/common.sh")],
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "PATH": str(self.environment / "bin") + os.pathsep + os.environ["PATH"],
                        "CI_COMMIT_SHA": self.sha,
                        "CI_PIPELINE_EVENT": "manual",
                        **overrides,
                    },
                )
                self.assertNotEqual(result.returncode, 0)
                if "CI_PIPELINE_EVENT" in overrides:
                    self.assertIn("Unsupported pipeline event", result.stdout)
                if "TEST_PROFILE" in overrides:
                    self.assertIn("Invalid TEST_PROFILE", result.stdout)


if __name__ == "__main__":
    unittest.main()
