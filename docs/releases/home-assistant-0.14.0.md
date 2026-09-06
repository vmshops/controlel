# Controlel Home Assistant integration 0.14.0

Status: candidate

## Summary

Integration 0.14.0 pins the not-yet-published Core candidate
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

- Required Core package: exactly `controlel==0.18.0`; publication is required before HA release.
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

## Candidate gate

Core 0.17.0 is public but lacks the active-reference and shutoff APIs this HA
candidate requires. Core 0.18.0 is not yet public. The required public-wheel
workflow must pass against actual PyPI bytes before HACS artifact validation
can succeed. Local checked-out-wheel tests provide development evidence only.

The candidate includes Water startup buffering, missing-state fault grace,
stable identity resolution, evidence/output failure isolation, transactional
activation handover, and stale interrupted-activation recovery. No automatic
valve reopening is added. Heating control behavior is unchanged.

Adapter/framework tests, deterministic HACS validation, lint/format checks,
and real HAOS installation testing remain required before separate release
approval. No `v0.14.0` tag or GitHub/HACS release exists from this preparation.
