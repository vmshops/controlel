# ADR-001: Core Engine independence from Home Assistant

Date:
2026-07-15

Status:
Accepted

## Context

Controlel must be deeply integrated with Home Assistant but must not depend on Home Assistant internal architecture.

The regulation engine must be usable with different platforms and hardware integrations.

## Decision

The Controlel Core Engine will not contain any Home Assistant specific code.

The Core Engine will communicate only with abstract internal interfaces.

Examples:

- Boiler
- Climate Valve
- Temperature Sensor
- Weather Provider
- Energy Meter

Home Assistant will be implemented as an integration layer.

## Consequences

Positive:

- Platform independence
- Easier testing
- Possibility to run outside Home Assistant
- Easier plugin development

Negative:

- More initial development complexity
- Additional abstraction layer
