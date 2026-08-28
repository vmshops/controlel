# Controlel Core 0.16.0

Status: published

Release: Controlel Core 0.16.0

## Summary

Core 0.16.0 carries the canonical configuration v3 backend required by the
completed Configure flow, Setup Wizard, and Heating/Settings surfaces:

- schema v3 models with explicit field ownership, editability, and defaults;
- draft, validation, conversion-review, and activation lifecycle contracts;
- greenfield Heating authoring and deterministic v2-to-v3 migration; and
- reference binding and health checks without inferring physical state.

## Frozen release boundary

- No runtime control algorithm, activation behavior change, or automatic
  migration beyond explicit v2-to-v3 conversion is included.
- Home Assistant integration 0.14.0 candidate pins this package exactly.

## Compatibility and publication order

- Python: 3.13 or newer.
- Runtime dependency remains only `pydantic>=2.0`.
- Immutable annotated Core tag: `core-v0.16.0`, resolving to
  `6a587728551a1ae8f9d04b8ddef8f2cde288a469`.
- Published to PyPI beginning at `2026-08-28T17:19:16Z`.
- Wheel: `controlel-0.16.0-py3-none-any.whl`, 262,788 bytes, SHA-256
  `1bd604429b8a655f6a4295f8b95378fafa194ff9c070eb884745a620cb3c0b8e`.
- Sdist: `controlel-0.16.0.tar.gz`, 185,466 bytes, SHA-256
  `6a132d3af66261b704d07e055305fe81d62c9648bbd075a3c66300c98cd3050a`.
- Both public files match the deterministic final artifacts bound to the tag.
