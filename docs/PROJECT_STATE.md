# Controlel Project State

This document records the current CONTROL-accepted canonical state of
Controlel. It is a navigation/state document, not a complete project history.

A worker, execution agent, Work run, review report, older plan, or historical
branch is not canonical merely because it exists. Newer explicit CONTROL
decisions take precedence.

## Implemented / shipped

### Controlel Core 0.18.0

- Public PyPI package: `controlel==0.18.0`.
- Release tag: `core-v0.18.0`.
- Exact release commit:
  `5ad5eca46046460c711510fbb09011b7db13b924`.
- The shipped HA integration pins the exact public Core dependency.

### Home Assistant integration 0.14.1

- Public release: `v0.14.1`.
- Exact release source:
  `0746c5cb0eced2350e1883f5f2cb5514040b9886`.
- Includes HACS readiness work and embedded brand assets.
- HACS default-repository submission is external/pending review and is not
  considered shipped default-HACS inclusion until upstream accepts it.

### Development Harness V2

- Status: implemented / shipped.
- Canonical integration checkpoint:
  `5efbb16b7e37d8aa11e3fba42557d9267d623e1b`.
- Role: default execution foundation for bounded Controlel work.
- For every task, CONTROL decides:
  - exact baseline/checkpoint;
  - READ-ONLY or WRITE mode;
  - exact worktree and branch;
  - FREE deterministic PowerShell/Git/WSL setup/preflight;
  - verification/test profile;
  - executor, model, and reasoning effort;
  - success criteria.
- Mandatory order:
  CONTROL decision -> FREE deterministic setup/preflight -> exact worktree and
  environment verified -> `=== PREFLIGHT OK ===` -> executor.
- `=== PREFLIGHT FAIL ===` means executor work does not start.
- Deterministic work is not sent unnecessarily to paid or limited models.
- Preferred Codex flow:
  FREE preflight prepares the exact worktree, then the user manually opens
  Codex in the ChatGPT app on that exact worktree and pastes the work prompt.
- Work is an explicit exception, not the standard coding workflow.

## Experimental

### Companion App telemetry ingestion

- Experimental branch/work exists at commit:
  `a26e83f`.
- It was built on an older Heating development baseline and must not be merged
  directly into the current canonical line.
- Any future integration requires deliberate forward-port/rebase/cherry-pick
  onto a current accepted baseline plus integration testing.

## Accepted / planned

### Home Assistant Core Compatibility Foundation

The project will remain technically Home-Assistant-Core-compatible where doing
so represents good engineering, even if upstream never accepts Controlel.

Current accepted direction:

- Bronze is the first external Core-contribution target.
- Internally, adopt relevant Silver/Gold/Platinum engineering practices where
  they materially improve correctness, lifecycle, testing, typing, recovery,
  or release quality.
- Native Home Assistant Configure/config-entry flows remain sufficient for
  essential structural configuration.
- Custom frontend is non-essential and must not become a runtime/configuration
  dependency for a stable Core-compatible subset.
- Modules must have explicit ownership and unrelated module failures must not
  unnecessarily disable healthy modules.

Accepted audit checkpoints:

- CORE-00A: accepted.
- CORE-00B: accepted.
- CORE-00C: next architecture decision checkpoint.

Planned implementation sequence before Multi-Zone:

1. Module Lifecycle Isolation V1.
2. Release Automation V2.
3. Public Package API V1.
4. CORE-01 Water Safety projection to a real Home Assistant Core checkout.
5. Reach `CORE PROJECTION: GREEN`.
6. After a Bronze-green, PR-ready Water slice exists, open a concise Home
   Assistant Architecture discussion about suitability/integration model.
7. Open a real upstream PR only if the concept/scope remains appropriate.

Water Safety is the provisional first Core projection candidate.
Heating may become a stronger upstream candidate after Multi-Zone/shared-source
maturity.

### Multi-Zone / whole-house Heating

- Accepted/planned after the Core Compatibility Foundation.
- The shipped single-zone model becomes the one-zone case of the future
  multi-zone architecture.
- Shared physical topology is separate from domain-specific grouping.
- Zone-local measurement/demand/confirmation remains below Heating.
- Shared source arbitration/protection remains above zones.
- Multi-Zone remains deterministic/static initially.

## Deferred

- AI control, learning, prediction, optimization, and automatic topology
  inference are deferred until the whole-house deterministic model is mature
  and there is sufficient real operational history.
- The old/custom wizard is not the canonical structural configuration authority.
  Native Home Assistant configuration remains primary.
- Higher IQS work that exists only to collect cosmetic/upstream points is
  deferred unless it brings material product value.

## Known limitations / technical debt

- Heating and Water currently have module-scoped configuration/runtime hosts
  but remain coupled at config-entry setup/unload/reload boundaries. Water
  failure can unnecessarily affect healthy Heating. This must be resolved
  before Multi-Zone.
- The public `controlel` PyPI package is built/verified in public CI but is not
  yet published from public CI. This is a known Home Assistant Bronze
  dependency-transparency blocker and a Release Automation V2 target.
- The HA adapter currently consumes some deep `controlel` package internals.
  A deliberately supported public package facade is planned before CORE-01.
- The known hassfest `CONFIG_SCHEMA` warning remains non-blocking and is not a
  Development Harness V2 regression.
- HACS default inclusion remains pending external upstream review.
- `docs/PROJECT_IDEAS.md` has not yet been bootstrapped; preserved ideas remain
  governed by CONTROL until that canonical document is created.
