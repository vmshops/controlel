# Development harness V2

The repository-owned development harness is the required entry point for a bounded Controlel task. It keeps task identity, execution location, environment identity, and verification composition explicit.

## Execution model

The canonical Git anchor is `C:\GitHub\Controlel\controlel`. An executor works in exactly one ordinary worktree at `C:\GitHub\Controlel\worktrees\<task-slug>`, on an explicit branch, from an explicit immutable baseline SHA. A task must never silently use the current anchor `HEAD` as its baseline.

Run preflight before editing and before verification. `Baseline` is always the exact baseline SHA; before editing, `HEAD` must equal it. After a clean local verification commit, pass that commit as `ExpectedHead`, while preflight still verifies that the baseline exists. It performs no cleanup, reset, stash, branch switch, or baseline selection. A preflight either ends with `=== PREFLIGHT OK ===` or `=== PREFLIGHT FAIL ===`.

```powershell
./scripts/agent/preflight.ps1 `
  -RepoAnchor C:\GitHub\Controlel\controlel `
  -Baseline <exact-baseline-sha> `
  -Mode WRITE `
  -Worktree C:\GitHub\Controlel\worktrees\<task-slug> `
  -Branch chore/<task-slug> `
  -Profile fast `
  -CorePython C:\path\to\python.exe
```

The command fails closed for a wrong repository/origin/baseline/HEAD, a dirty execution worktree, an active Git operation, branch mismatch or a protected write branch. For HA profiles, supply the WSL distribution and the explicitly selected HA environment.

## Environments and HA composition

Windows/Core profiles require Python 3.14.x. Home Assistant framework profiles run only in WSL/Linux through `scripts/agent/ha-test.sh`; the runner requires all of `--worktree`, `--profile`, and `--environment`.

Each HA environment has a `.controlel-harness-v2.json` fingerprint. Initialize an unused pre-created environment exactly once with `scripts/agent/prepare-ha-environment.sh --worktree <wsl-worktree> --baseline <exact-baseline-sha> --profile <...> --environment <venv>`. It binds the profile, baseline ancestry, WSL worktree path, and SHA-256 of `requirements/ha-test.txt`; it refuses to overwrite an existing fingerprint. A mismatch is a hard failure, never an invitation to reuse or mutate an ambiguous environment.

`checked-out-wheel` builds a wheel from the selected worktree, installs it with `--no-deps`, and delegates provenance/public-surface validation to `scripts/ci/verify_public_core.py --development-wheel`. Framework tests run with `CONTROLEL_FRAMEWORK_COMPOSITION=checked-out-wheel`.

`source-candidate` is a separate task-scoped environment. It refuses an installed `controlel` distribution and binds imports to that selected worktree's `src/`; it cannot fall back to a checked-out wheel or public distribution.

## Verification profiles

`verify.ps1` always invokes preflight first, then delegates to existing tests instead of duplicating product checks.

- `fast`: architecture self-tests.
- `core`: Core test suite.
- `ha-adapter`: HA adapter tests using checked-out-wheel.
- `ha-framework`: HA framework tests using checked-out-wheel.
- `ha-source`: HA adapter tests using task-scoped source/candidate composition.
- `packaging`: existing packaging tests and release-artifact contracts.

No harness command publishes, pushes, tags, deploys, or changes release state. Record the selected baseline, profile, exact command, and result in the task evidence before asking CONTROL to accept or reject the work.
