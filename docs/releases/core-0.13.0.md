# Controlel Core 0.13.0

Status: candidate

Release: Controlel Core 0.13.0

## Summary

Core 0.13.0 adds the public, versioned, read-only Frontend API v1 developed
after the published Core 0.12.0 boundary. The API projects immutable host
evidence for overview, heating, diagnostics, and setup consumers without
mutating runtime state.

## Frontend API v1 public boundary

The distribution includes `controlel.frontend_api`,
`controlel.frontend_api.v1`, `controlel.frontend_api.v1.models`, and
`controlel.frontend_api.v1.provider`. The v1 package exports immutable evidence
and response models, JSON-safe response projection, and the passive
`FrontendApiProviderV1`.

The provider preserves the distinction between what was requested, the command
outcome, reported source state, and physical state. Physical state remains
`unknown` because permission, dispatch, and controller reports do not establish
physical reality. Command outcomes remain explicit and distinct:
`dispatched`, `failed`, `suppressed`, `deferred`, and `held`.

## Frozen release boundary

- No write endpoints, command callbacks, or runtime mutation are exposed.
- No activation or reconciliation behavior is added.
- No heating, heat-delivery, source-control, protection, or safety behavior is
  changed.
- No future Core 0.14 work is included.

## Compatibility and publication order

- Python: 3.13 or newer.
- Runtime dependency remains only `pydantic>=2.0`.
- Home Assistant integration 0.12.0 remains pinned to public Core 0.12.0.
- The immutable Core tag will be `core-v0.13.0` after final review.
- Build, clean-install, provenance, tag, PyPI publication, and independent
  public-artifact verification must complete before a Home Assistant
  integration may pin Core 0.13.0.
