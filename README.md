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

Core package version: 0.2.0 (published and immutable)

Home Assistant integration candidate version: 0.4.0

Use the latest published release for HACS custom-repository installation.
Version `0.4.0` is under development and has not been tagged or published.
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
dependency `controlel==0.2.0`; users must not install the core manually.
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
the target, plus command-based minimum on/off times of 10/5 minutes. Existing
entries resolve all four settings to zero until the user explicitly changes
them. The controller preserves its last logical demand within the deadband and
reevaluates current demand at a lockout deadline instead of replaying a stored
command. Safety-disable commands bypass minimum-on protection; safety-enable
commands remain subject to minimum-off protection.

Each entry creates one `Controlel — <Zone name>` device with operational and
diagnostic sensors. They expose the normalized temperature and target,
measurement validity and age, demand, safety grace/timeout state, the latest
decision and reason, requested command and dispatch outcome, failure flags,
and runtime/core versions. Demand and a dispatched service call are not proof
that the physical heat source changed state. The target remains writable only
through **Configure**. Diagnostics include the immutable current snapshot and
a maximum 20-record in-memory decision trace; neither survives reconstruction.

The integration manifest requires the exact public core release
`controlel==0.2.0`. A supported custom-component deployment can therefore let
Home Assistant obtain the core dependency automatically; users do not need to
install the core manually. Editable installation remains available for local
source compatibility testing. The core test suite does not require Home
Assistant, while Home Assistant framework tests use separate local-source and
public-package compositions against the same immutable core `0.2.0` release.

Framework compatibility is tested against Home Assistant `2026.7.3` with
`pytest-homeassistant-custom-component==0.13.347` on Python 3.14.2 or newer.
The isolated, hashed environment is defined by `requirements/ha-test.in` and
`requirements/ha-test.txt`; setup and suite commands are in the
[development guide](docs/development/DevelopmentGuide.md). The compatibility
harness is separate from HACS release validation. HACS metadata and
deterministic release packaging are prepared for `0.4.0`, but that candidate
has not been published and no default-store publication exists.

## Core package artifacts

The reusable core is published as the `controlel` distribution and import
package at version `0.2.0`. Its static version source and PEP 517 build
configuration live in `pyproject.toml`; normal installation depends only on
Pydantic. Packaging validation builds one wheel and one sdist, inspects their
contents, and installs the wheel into a clean environment outside the checkout.

Core versions `0.1.0` and `0.2.0` are published on PyPI and immutable. Future
core corrections require a new version; rebuilt artifacts for an already
published version must never be uploaded.
Repository packaging CI remains validation-only and contains no publication
automation. See the [core release guide](docs/development/ReleaseGuide.md) for
the published release record, build validation, and version separation.
