# Controlel Core 0.13.0

Status: published

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
- Home Assistant integration 0.13.0 candidate pins public Core 0.13.0 exactly.
- Immutable annotated Core tag: `core-v0.13.0`, resolving to
  `0fdaaa21341e03e9c01f33acfdac8197929fa841`.
- Published to PyPI beginning at `2026-08-24T08:54:39.374314Z`.
- Wheel: `controlel-0.13.0-py3-none-any.whl`, 237,489 bytes, SHA-256
  `233f395993dd9b6b0f16fa3cf267b61ec332e2e7f36aa17d84ac37a1fa925ff2`.
- Sdist: `controlel-0.13.0.tar.gz`, 165,233 bytes, SHA-256
  `001e69c0f0fd3bdfeecc751472689d2d59d27b6f8ff0e4b3cde7d3b1cd08c164`.
- Both public files match the final deterministic artifacts bound to the tag.
- Home Assistant integration 0.13.0 consumes this public boundary through an
  independently verified public-package composition.
