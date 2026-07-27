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

Core version: 0.1.0

Home Assistant integration version: 0.1.1

## Home Assistant development integration

The reusable core remains under `src/controlel`. The first Home Assistant host
is a custom component under `custom_components/controlel`; its dependency
direction is strictly custom component to core.

The integration supports one config entry, one zone, one explicitly bound
temperature sensor, and one shared heat source controlled through configured
enable and disable service calls. It uses a dedicated single-worker executor
for every synchronous `ControlRuntime` operation. No core method runs on Home
Assistant's event-loop thread.

The integration manifest requires the exact public core release
`controlel==0.1.0`. A supported custom-component deployment can therefore let
Home Assistant obtain the core dependency automatically; users do not need to
install the core manually. Editable installation remains available for local
source compatibility testing. The core test suite does not require Home
Assistant, while Home Assistant framework tests use separate local-source and
public-package compositions.

Framework compatibility is tested against Home Assistant `2026.7.3` with
`pytest-homeassistant-custom-component==0.13.347` on Python 3.14.2 or newer.
The isolated, hashed environment is defined by `requirements/ha-test.in` and
`requirements/ha-test.txt`; setup and suite commands are in the
[development guide](docs/development/DevelopmentGuide.md). This compatibility
harness does not make the integration HACS-ready. No HACS metadata, integration
release, or default-store publication is provided.

## Core package artifacts

The reusable core is prepared as the `controlel` distribution and import
package at version `0.1.0`. Its static version source and PEP 517 build
configuration live in `pyproject.toml`; normal installation depends only on
Pydantic. Packaging validation builds one wheel and one sdist, inspects their
contents, and installs the wheel into a clean environment outside the checkout.

Core `0.1.0` is published on PyPI and is immutable. Future core corrections
require a new version; rebuilt local `0.1.0` artifacts must never be uploaded.
Repository packaging CI remains validation-only and contains no publication
automation. See the [core release guide](docs/development/ReleaseGuide.md) for
the published release record, build validation, and version separation.
