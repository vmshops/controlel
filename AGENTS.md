# Controlel Agent Guidelines

## Project purpose

Controlel is a general heating control platform.

The goal is not to create device-specific automations.
The goal is a robust, explainable and safe heating control architecture
supporting different homes, boilers, radiators and actuators.

---

# Core architecture principles

## Separation of layers

Always keep these responsibilities separated:

Zone:
- comfort targets
- occupancy context
- room demand

Heat Delivery:
- actuator strategy
- zone heat delivery

Source Control:
- boiler permission
- anti-cycling
- minimum on/off protection
- safety

Future Boiler Optimization:
- water temperature
- efficiency optimization

Never mix these layers.

---

# Truthfulness rules

Never infer physical reality.

Examples:

A successful command is not physical confirmation.

Wrong:
"Valve opened to 50%, therefore valve is 50% open."

Correct:
"Command requested 50%, physical position unknown."

Wrong:
"Boiler enable command means burner is running."

Correct:
"Heat source permission was granted."

Unknown is not false.

---

# Event-driven architecture

Prefer:
- events
- explicit state transitions
- deterministic deadlines

Avoid:
- unnecessary polling
- hidden background loops
- periodic evaluation without architectural reason

---

# Safety

Safety behavior always has priority.

Never bypass:
- source protection
- anti-cycling
- minimum on/off times
- deferred commands
- failure handling

---

# Adaptive behavior

Adaptive or learning behavior must be evidence based.

Never implement:
- blind boost logic
- maximum output assumptions
- reactions to single measurements

Observation comes before adaptation.

---

# Commands and observations

Keep separate:

Command:
"What we requested"

Observation:
"What the system reported"

Assessment:
"What we conclude from evidence"

Decision:
"What we choose to do"

Never merge these concepts.

---

# Compatibility

Existing behavior is valuable.

Before changing existing logic:

- understand current contracts
- preserve backward compatibility
- add tests
- avoid unnecessary redesign

---

# Testing philosophy

Behavior changes require tests.

Prefer:
- immutable domain models
- explicit state
- deterministic tests
- explainable failures

---

# Development Harness V2 execution governance

Development Harness V2 is the default execution foundation for bounded
Controlel work.

For every task, CONTROL decides and records:

- the exact baseline/checkpoint
- READ-ONLY or WRITE mode
- the exact worktree and branch
- the FREE deterministic PowerShell/Git/WSL setup and preflight
- the verification/test profile
- the executor, model, and reasoning effort (see Executor and model routing)
- the success criteria

Execution order is mandatory:

1. CONTROL decides the task contract.
2. FREE deterministic setup prepares the exact worktree, branch, and required
   environment.
3. The fail-closed preflight verifies repository, origin, baseline, branch,
   worktree, Git-operation state, protected-branch safety, and required
   environment.
4. The preflight must finish with exactly `=== PREFLIGHT OK ===`. On
   `=== PREFLIGHT FAIL ===`, executor work must not start.
5. Only after `=== PREFLIGHT OK ===` is the selected executor started.

Do not send deterministic work unnecessarily to paid or limited models.

Work is an explicit exception, not the standard coding workflow. Do not hand a
task to Work or another executor before the FREE setup/preflight has prepared
and verified the exact execution worktree.

The preferred Codex flow is:

1. FREE setup/preflight prepares the exact worktree;
2. require `=== PREFLIGHT OK ===`;
3. the user manually opens Codex in the ChatGPT app on that exact worktree and
   pastes the task prompt.

For normal development, do not auto-open VS Code and do not create
executor-managed `Users/.codex` worktrees.

---

# Executor and model routing

CONTROL chooses the executor. For a technical or coding task recommendation,
state:

PLATFORMA:
MODEL:
ÚSILÍ:
ÚKOL:
PROČ:

Use the cheapest and smallest model that can reliably do the task. Use Grok
or Astra when the task is actually complex. Do not pass work between models
without a new CONTROL decision. Worker and reviewer output is evidence only
until CONTROL accepts it. Repository, worktree, preflight, no-push, and
no-merge safety rules remain in force.

- ChatGPT GPT-5.6 Sol: CONTROL, architecture, specifications and contracts,
  analysis and debugging, safe procedures, acceptance and review.
- ChatGPT Work / Codex GPT-6 Astra: strongest escalation for exceptionally
  difficult coding, repo-wide work, or debugging. Not the default.
- Cursor Grok 4.7: complex multi-file implementation, difficult fixes,
  migrations and refactors, and autonomous repository or terminal work.
- Cursor Composer 2.5: normal small and medium implementation, tests, and
  straightforward fixes or refactors.
- Cursor Claude Opus 5.5: targeted independent or critical review and a
  second opinion.
- Cursor Gemini 3.8 Flash: cheap large-context search, summarization,
  classification, and mechanical analysis.
- ModelArk GLM-5.2: bounded module, bug, patch, tests, or limited refactor.
- local Qwen3-Coder-30B-A3B-Instruct: free non-thinking helper for short,
  precise, bounded implementation, test, parser, DTO, SQL, shell, PowerShell,
  diff, or boilerplate tasks. Stop if it starts looping.
- GitHub Copilot Free: autocomplete and small local coding assistance.

---
# When uncertain

Prefer:

Explicit state over assumptions.

Diagnostics over magic.

Safe fallback over aggressive action.

Simple architecture over premature intelligence.

## Home Assistant test environment

Home Assistant framework tests MUST run in WSL/Linux.

Use the repository-owned `scripts/agent/ha-test.sh` runner with an explicit
worktree, profile, and fingerprinted task-scoped HA environment. See
`docs/development/AgentWorkflow.md`. The historical machine-local runner is
not canonical infrastructure.

Use Windows/Bionic for:
- editing files
- git status and diff
- git commit
- git push

Use WSL/Linux for:
- Home Assistant framework tests
- Linux/CI reproduction
- Home Assistant Python integration verification

Run Home Assistant tests from Bionic via the repository runner in WSL; do not
let the runner infer a worktree from the shell current directory.

Never use a Windows `.venv-ha/Scripts/python.exe` environment for Home Assistant framework tests.

Do not add Windows-specific compatibility hacks for Home Assistant tests, including:
- fcntl stubs
- resource stubs
- asyncio/event-loop policy changes
- pytest/conftest changes whose only purpose is native Windows compatibility

For source/candidate work, use a dedicated environment bound to one selected
source worktree; never share an editable Controlel installation across tasks.

Published Core `0.18.0` is the current public Core release. Home Assistant
public-composition tests must install exact `controlel==0.18.0` from PyPI and
verify its published artifact identities and imported public surface.
Do not bypass, weaken, or rewrite public-composition tests.

If a Home Assistant test fails:
1. reproduce it using the canonical WSL runner;
2. treat the WSL/Linux result as authoritative;
3. do not attempt to repair the Windows HA test environment.

Git operations for this Windows-created worktree should remain on Windows because its `.git` worktree metadata contains Windows paths.
Do not try to repair or rewrite that metadata from WSL.
