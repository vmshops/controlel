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

Version: 0.1.0

## Home Assistant development integration

The reusable core remains under `src/controlel`. The first Home Assistant host
is a custom component under `custom_components/controlel`; its dependency
direction is strictly custom component to core.

The integration supports one config entry, one zone, one explicitly bound
temperature sensor, and one shared heat source controlled through configured
enable and disable service calls. It uses a dedicated single-worker executor
for every synchronous `ControlRuntime` operation. No core method runs on Home
Assistant's event-loop thread.

The manifest intentionally has `requirements: []`. The custom component is
therefore deployable only where the local `controlel` core package is already
installed, such as an editable development installation. A future packaging
milestone must publish and pin the core package before normal HACS deployment.
The core test suite does not require Home Assistant; Home Assistant framework
tests require a separate integration-test environment.

Framework compatibility is tested against Home Assistant `2026.7.3` with
`pytest-homeassistant-custom-component==0.13.347` on Python 3.14.2 or newer.
The isolated, hashed environment is defined by `requirements/ha-test.in` and
`requirements/ha-test.txt`; setup and suite commands are in the
[development guide](docs/development/DevelopmentGuide.md). This compatibility
harness does not make the integration HACS-ready: the core package is not
published, `manifest.json` intentionally has `requirements: []`, and no HACS
metadata is provided.
