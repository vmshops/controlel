# Controlel Home Assistant integration 0.14.0

Status: published

## Summary

Integration 0.14.0 pins the published Core
`controlel==0.18.0` package and ships canonical configuration v3 Configure,
Setup Wizard, Heating/Settings, and Water Safety surfaces for Home Assistant.
It connects the public Frontend API v1 and v3 lifecycle contracts to
authenticated WebSocket commands and manages the sidebar panel across setup,
reload, unload, and partial-failure cleanup.

## Included stack

- Canonical configuration v3 draft, validation, conversion review, and activation.
- Setup Wizard and Heating/Settings surfaces over authenticated WebSocket commands.
- Water Safety setup, activation, diagnostics, and Frontend API v1 projection.
- Frontend API v1 bridge and read-only overview, heating, diagnostics, setup, and water safety views.
- Home Assistant sidebar panel lifecycle with packaged runtime assets.
- English and Czech UI localization foundations.
- Explicit loading, disconnected, error, and unknown semantics.

## Compatibility

- Required Core package: exactly `controlel==0.18.0`.
- Home Assistant: 2026.7.3 or newer.
- Config-entry version remains 1.
- Existing version-1 entries retain their runtime/configuration path and do
  not require an automatic migration.

## Safety and scope boundary

Configure, Setup Wizard, Heating/Settings, and Water Safety use explicit
lifecycle contracts. No runtime control algorithm change, blind boost logic, or
inferred physical state is included. Commands, observations, assessments, and
decisions remain separate, and unknown physical state is not treated as false
or inferred from command success.

## Published release boundary

Core 0.18.0 is public and supplies the active-reference and shutoff APIs this
integration requires. Public-wheel validation passed against actual PyPI bytes
before the HACS artifact was released.

The release includes Water startup buffering, missing-state fault grace,
stable identity resolution, evidence/output failure isolation, transactional
activation handover, and stale interrupted-activation recovery. No automatic
valve reopening is added. Heating control behavior is unchanged.

The immutable integration tag is `v0.14.0`, resolving to
`fea69d194be1b660658bd15f708df139bee67c57`. The GitHub release includes the
installable `controlel.zip` HACS asset. Version 0.14.1 is a separate,
unpublished distribution/metadata readiness candidate.
