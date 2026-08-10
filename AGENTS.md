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
