# Controlel Home Assistant integration 0.14.0

Status: candidate

## Summary

Integration 0.14.0 pins the independently verified public
`controlel==0.16.0` package and ships canonical configuration v3 Configure,
Setup Wizard, and Heating/Settings surfaces for Home Assistant. It connects the
public Frontend API v1 and v3 lifecycle contracts to authenticated WebSocket
commands and manages the sidebar panel across setup, reload, unload, and
partial-failure cleanup.

## Included stack

- Canonical configuration v3 draft, validation, conversion review, and activation.
- Setup Wizard and Heating/Settings surfaces over authenticated WebSocket commands.
- Frontend API v1 bridge and read-only overview, heating, diagnostics, and setup views.
- Home Assistant sidebar panel lifecycle with packaged runtime assets.
- English and Czech UI localization foundations.
- Explicit loading, disconnected, error, and unknown semantics.

## Compatibility

- Required Core package: exactly `controlel==0.16.0` from public PyPI.
- Home Assistant: 2026.7.3 or newer.
- Config-entry version remains 1.
- Existing version-1 entries retain their runtime/configuration path and do
  not require an automatic migration.

## Safety and scope boundary

Configure, Setup Wizard, and Heating/Settings use explicit lifecycle contracts.
No runtime control algorithm change, blind boost logic, or inferred physical
state is included. Commands, observations, assessments, and decisions remain
separate, and unknown physical state is not treated as false or inferred from
command success.

## Candidate gate

Core 0.16.0 is public and its wheel and sdist identities match the immutable
tag-bound provenance. The HA candidate must pass adapter and framework suites
against the installed public package, deterministic HACS build and strict archive
validation, lint, format checks, and final artifact inspection. Do not create
`v0.14.0` or publish the GitHub/HACS release during candidate preparation.
