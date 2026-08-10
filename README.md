# Controlel

Adaptive intelligent heating control platform.

## Vision

Controlel is a modular, explainable and adaptive heating regulation platform designed for Home Assistant integration.

The goal is to create a reliable heating controller capable of optimizing comfort, efficiency and condensation performance while maintaining safety and transparency.

## Main principles

- Safety first
- Explainable decisions
- Modular architecture
- Hardware independence
- Configuration through UI
- Open-source ready
- Adaptive regulation

## Status

Project phase: Home Assistant one-zone host vertical slice

Core package candidate version: 0.4.0 (unpublished; public 0.3.0 remains immutable)

Home Assistant integration candidate version: 0.7.0 (Phase C; current Phase A manifest remains 0.6.0)

Use the latest published release for HACS custom-repository installation.
Core `0.3.0` is published and immutable. Milestone 28 prepares core `0.4.0`
without publication. Until that candidate is separately approved and public,
the integration manifest remains `0.6.0` and pins exactly
`controlel==0.3.0`; integration `0.7.0` is a Phase C candidate only.
Controlel is not listed in the default HACS store.

## Home Assistant installation

The supported distribution uses the public repository
`https://github.com/vmshops/controlel` as a HACS custom repository. The primary
installation flow is:

1. In HACS, open the menu and select **Custom repositories**.
2. Add `https://github.com/vmshops/controlel` with category **Integration**.
3. Download the latest released integration and restart Home Assistant.
4. Open **Settings > Devices & services > Add integration** and select
   **Controlel**.

The integration manifest makes Home Assistant install the exact public core
dependency `controlel==0.3.0`; users must not install the core manually.
Detailed prerequisites, configuration, safety behavior, manual installation,
upgrades, removal, and current limitations are in the
[Home Assistant installation guide](docs/operations/HomeAssistantInstallation.md).

## Home Assistant development integration

The reusable core remains under `src/controlel`. The first Home Assistant host
is a custom component under `custom_components/controlel`; its dependency
direction is strictly custom component to core.

The integration supports one config entry, one zone, one explicitly bound
temperature sensor, and one shared heat source. New entries use a filtered
temperature selector, generated stable IDs, safe timing defaults, and a simple
controlled-switch mode. Existing entries can be edited through **Configure**;
advanced mode preserves separate enable and disable service calls. Options
updates fully unload and rebuild the runtime. It uses a dedicated single-worker
executor for every synchronous `ControlRuntime` operation. No core method runs
on Home Assistant's event-loop thread.

New entries default to asymmetric hysteresis of 0.3 Â°C below and 0.1 Â°C above
the target, a two-minute heat-demand confirmation interval, plus command-based
minimum on/off times of 10/5 minutes. Existing entries resolve all five
settings to zero until the user explicitly changes them. The controller
preserves its last logical demand within the deadband and
reevaluates current demand at a lockout deadline instead of replaying a stored
command. Safety-disable commands bypass minimum-on protection; safety-enable
commands remain subject to minimum-off protection.

Source observability distinguishes a passive protection boundary from an
active lockout. `earliest_next_enable_time` and
`earliest_next_disable_time` may exist when no command is blocked. Active
lockout and deferred-command fields exist only while the current aggregate
demand requests a transition that protection prevents. A deadline callback
reevaluates current demand and protection instead of replaying a stored
command. Successful enable/disable dispatch timestamps are command evidence,
not physical boiler feedback; Controlel does not infer whether a burner or
boiler is physically running.

Each entry creates one `Controlel — <Zone name>` device with a translated
operational summary and stable operational/diagnostic entities. The summary
describes logical demand, safety, deferred commands, requested commands, and
command outcomes; it never claims physical heat-source state. Configured
durations remain visible, while deadline and remaining entities are unavailable
when their countdown is inactive.

The Options Flow offers Basic, Detailed, and Debug diagnostic profiles. New
0.5.0 and later entries default to Basic. Existing entries without a stored profile
resolve to Detailed, preserving periodic operational timing visibility without
a setup-time migration write. Basic refreshes presentation on meaningful
runtime events and retains 20 trace records; Detailed refreshes active
countdowns every 10 seconds and retains 100; Debug refreshes only active
countdown entities every second and retains 500. Debug expires after
60 minutes by default and returns to the previous Basic/Detailed profile, or can
be kept active until manually changed. Profiles affect presentation, logging,
and in-memory evidence only—not regulation.

The integration manifest requires the exact public core release
`controlel==0.3.0`. A supported custom-component deployment can therefore let
Home Assistant obtain the core dependency automatically; users do not need to
install the core manually. Editable installation remains available for local
source compatibility testing. The core test suite does not require Home
Assistant, while Home Assistant framework tests use separate local-source and
public-package compositions against the same immutable core `0.3.0` release.

Framework compatibility is tested against Home Assistant `2026.7.3` with
`pytest-homeassistant-custom-component==0.13.347` on Python 3.14.2 or newer.
The isolated, hashed environment is defined by `requirements/ha-test.in` and
`requirements/ha-test.txt`; setup and suite commands are in the
[development guide](docs/development/DevelopmentGuide.md). The compatibility
harness is separate from HACS release validation. HACS metadata and
deterministic release packaging are prepared for `0.6.0`, but that candidate
has not been published and no default-store publication exists.

## Core package artifacts

The reusable core is published as the `controlel` distribution and import
package at version `0.3.0`. Its static version source and PEP 517 build
configuration live in `pyproject.toml`; normal installation depends only on
Pydantic. Packaging validation builds one wheel and one sdist, inspects their
contents, and installs the wheel into a clean environment outside the checkout.

Core versions `0.1.0`, `0.2.0`, and `0.3.0` are published on PyPI and immutable. Future
core corrections require a new version; rebuilt artifacts for an already
published version must never be uploaded.
Repository packaging CI remains validation-only and contains no publication
automation. See the [core release guide](docs/development/ReleaseGuide.md) for
the published release record, build validation, and version separation.

## Zone heat-demand confirmation

Core `0.3.0` inserts a zone-owned confirmation policy after hysteresis
and before `IdentityDemandArbitrator`. Positive-duration heat demand must remain
continuous until its deadline; the deadline reevaluates current hysteresis
demand rather than replaying stored state. No-heat demand clears immediately.
Invalid, unavailable, stale, or future-dated input cancels a pending interval,
and valid recovery starts a complete new interval. Zero duration preserves
legacy immediate behavior.

This filter is separate from heat-source minimum-off protection and does not
detect an open window. The shared source policy consumes confirmed aggregate
demand only. Pending state is not persisted across reload or restart, and no
state claims that a physical heat source is on or off.
