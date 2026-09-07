"""Repository-owned harness contracts stay explicit and non-publishing."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_harness_has_explicit_fail_closed_inputs_and_terminal_markers() -> None:
    preflight = (ROOT / "scripts" / "agent" / "preflight.ps1").read_text(encoding="utf-8")
    for value in ("RepoAnchor", "Baseline", "Mode", "Worktree", "Branch", "Profile", "=== PREFLIGHT OK ===", "=== PREFLIGHT FAIL ==="):
        assert value in preflight
    for value in ("execution worktree is dirty", "protected branch", "active Git operation", "unexpected origin"):
        assert value in preflight
    assert "git reset" not in preflight
    assert "git stash" not in preflight


def test_ha_runner_requires_explicit_isolated_composition_and_fingerprint() -> None:
    runner = (ROOT / "scripts" / "agent" / "ha-test.sh").read_text(encoding="utf-8")
    for value in ("--worktree", "--profile", "--environment", ".controlel-harness-v2.json", "checked-out-wheel", "source-candidate"):
        assert value in runner
    assert "CONTROLEL_FRAMEWORK_COMPOSITION=checked-out-wheel" in runner
    assert "verify_public_core.py --development-wheel" in runner
    assert "controlel-ui-local" not in runner
    preparer = (ROOT / "scripts" / "agent" / "prepare-ha-environment.sh").read_text(encoding="utf-8")
    assert "refusing to overwrite existing fingerprint" in preparer


def test_harness_docs_do_not_make_machine_local_paths_canonical() -> None:
    documentation = (ROOT / "docs" / "development" / "AgentWorkflow.md").read_text(encoding="utf-8")
    assert "<task-slug>" in documentation
    assert "exact baseline SHA" in documentation
    assert "controlel-ui-local" not in documentation
