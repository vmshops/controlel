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

# When uncertain

Prefer:

Explicit state over assumptions.

Diagnostics over magic.

Safe fallback over aggressive action.

Simple architecture over premature intelligence.

## Home Assistant test environment

Home Assistant framework tests MUST run in WSL/Linux.

Canonical WSL test runner:

`~/bin/controlel-ha-test`

Windows worktree:

`C:\GitHub\Controlel\controlel-ui-local`

WSL view of the worktree:

`/mnt/c/GitHub/Controlel/controlel-ui-local`

Use Windows/Bionic for:
- editing files
- git status and diff
- git commit
- git push

Use WSL/Linux for:
- Home Assistant framework tests
- Linux/CI reproduction
- Home Assistant Python integration verification

Run Home Assistant tests from Bionic with:

`wsl.exe -d Ubuntu -- bash -lc "~/bin/controlel-ha-test <pytest arguments>"`

Never use a Windows `.venv-ha/Scripts/python.exe` environment for Home Assistant framework tests.

Do not add Windows-specific compatibility hacks for Home Assistant tests, including:
- fcntl stubs
- resource stubs
- asyncio/event-loop policy changes
- pytest/conftest changes whose only purpose is native Windows compatibility

For local Frontend API development, use the local editable Controlel source installed in the canonical WSL environment.

Published Core `0.14.0` contains Frontend API v1. Home Assistant 0.13.0
public-composition tests must install exact `controlel==0.14.0` from PyPI and
verify its published artifact identities and imported public surface.
Do not bypass, weaken, or rewrite public-composition tests.

If a Home Assistant test fails:
1. reproduce it using the canonical WSL runner;
2. treat the WSL/Linux result as authoritative;
3. do not attempt to repair the Windows HA test environment.

Git operations for this Windows-created worktree should remain on Windows because its `.git` worktree metadata contains Windows paths.
Do not try to repair or rewrite that metadata from WSL.
