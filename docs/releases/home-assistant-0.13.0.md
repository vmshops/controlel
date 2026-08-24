# Controlel Home Assistant integration 0.13.0

Status: candidate

## Summary

Integration 0.13.0 pins the independently verified public
`controlel==0.13.0` package and ships the first real-data, read-only Controlel
sidebar experience for Home Assistant. It connects the public Frontend API v1
boundary to authenticated read-only WebSocket commands and manages the sidebar
panel across setup, reload, unload, and partial-failure cleanup.

## Included stack

- Frontend API v1 bridge and authenticated read-only WebSocket commands.
- Home Assistant sidebar panel lifecycle with packaged runtime assets.
- Real-data overview, heating, diagnostics, and setup views.
- English and Czech UI localization foundations.
- Explicit loading, disconnected, error, and unknown semantics.
- Explicit demo entry points for development only; failed real requests never
  silently fall back to mock data.

## Compatibility

- Required Core package: exactly `controlel==0.13.0` from public PyPI.
- Home Assistant: 2026.7.3 or newer.
- Config-entry version remains 1.
- Existing version-1 entries retain their runtime/configuration path and do
  not require an automatic migration.

## Safety and scope boundary

The Frontend API, WebSocket commands, and panel are read-only observation
surfaces. No write APIs, runtime activation, reconciliation, UI redesign, or
heating/control behavior changes are included. Commands, observations,
assessments, and decisions remain separate, and unknown physical state is not
treated as false or inferred from command success.

## Candidate gate

Core 0.13.0 is public and its wheel and sdist identities match the immutable
tag-bound provenance. The HA candidate must pass adapter and canonical WSL
framework suites against that installed public package, frontend Node tests,
deterministic HACS build and strict archive validation, lint, type checks, and
final artifact inspection. Do not create `v0.13.0` or publish the GitHub/HACS
release during candidate preparation.
