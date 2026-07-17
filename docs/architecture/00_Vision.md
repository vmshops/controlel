# Controlel Vision

**Version:** 1.0 (Draft)

---

# Mission

Controlel is an open-source intelligent heating control platform focused on safety, efficiency, transparency and long-term maintainability.

Its purpose is not only to automate heating but to continuously make better decisions using real data from the building while always allowing the user to understand and control those decisions.

Controlel should operate as an independent heating control platform which can integrate with Home Assistant, OpenTherm, MQTT and other automation systems without becoming dependent on any specific ecosystem.

---

# Vision

Traditional thermostats answer one question:

> Should the boiler heat?

Controlel answers many questions:

* Why should the boiler heat?
* How much should it heat?
* Is this the most efficient moment?
* Can condensation efficiency be improved?
* Can boiler cycling be reduced?
* Is another zone likely to request heat soon?
* Is solar gain expected?
* Is hot water currently being heated?
* Is the system behaving normally?

The objective is to continuously optimize the complete heating system rather than simply switching a boiler on and off.

---

# Core Principles

## Safety First

Safety has higher priority than comfort.

When uncertainty exists, Controlel always selects the safest valid behaviour.

---

## Explainability

Every decision must be explainable.

No action may occur without a recorded reason.

Every boiler command, valve change or temperature adjustment must be traceable.

---

## Human Control

The user always remains in control.

Manual operation must always be available.

Automatic control can always be disabled.

---

## Fail Safe

Every intelligent feature must have a deterministic fallback.

If adaptive regulation fails, the platform automatically switches to a simpler and verified operating mode.

Heating must continue.

---

## Platform First

Controlel is not a Home Assistant automation.

Controlel is not an OpenTherm controller.

Controlel is not a thermostat.

Controlel is a heating control platform.

Integrations are plugins.

The control logic remains independent.

---

## Data Driven

Every optimization should be based on measured data.

Assumptions are allowed only until enough measurements exist.

Learning is based on observations, not guesses.

---

## Modular Design

Every subsystem should be replaceable.

Examples include:

* Boiler driver
* Valve driver
* Weather provider
* Dashboard
* Database
* Notification system

Replacing one module must not require changes in the remaining system.

---

## Predictable Behaviour

The platform should always behave consistently.

Unexpected behaviour is considered a defect.

---

# Long-Term Goal

Controlel should become an extensible platform capable of controlling heating systems of different sizes while remaining understandable, testable and safe.

The project values reliability above complexity.

A feature is only considered complete when it is:

* documented,
* tested,
* observable,
* configurable,
* explainable.

Only then is it ready for production.
