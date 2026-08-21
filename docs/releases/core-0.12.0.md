# Controlel Core 0.12.0

Status: published

Release: Controlel Core 0.12.0

## Summary

Core 0.12.0 packages the observational anomaly, deterministic Shadow Runtime,
and module-neutral Setup / Discovery / Import foundations developed after the
published Core 0.11.0 boundary.

## Setup public boundary

The wheel includes immutable Setup authority contracts, deterministic canonical
configuration serialization, draft and activation-attempt repository contracts,
conservative Home Assistant discovery/reference resolution, Heating
recommendation/validation, and the host-facing resumable setup DTO/service
boundary. The Home Assistant adapters remain optional infrastructure: importing
them does not import or require Home Assistant itself.

Canonicalization creates an inactive immutable revision. Core 0.12.0 does not
expose runtime activation through the setup host, does not merge legacy options
with canonical configuration, and does not add setup decisions to control.
In short, runtime activation is not exposed in this release.

## Other included foundations

- Anomaly v1 remains an observability feature, not a control feature.
- Shadow Runtime v0.1 provides deterministic behavioral simulation and replay,
  without building-physics modelling or production control coupling.
- Source reconciliation waits for new reported evidence after a successful
  corrective command while retaining bounded retry after failed dispatch.

## Compatibility and publication order

- Python: 3.13 or newer.
- Runtime dependency remains only `pydantic>=2.0`.
- Intended Home Assistant integration candidate: 0.12.0.
- Immutable annotated Core tag: `core-v0.12.0`, resolving to
  `992b291902318f4f0406c4b368282ff3a7ed4dbf`.
- Published to PyPI beginning at `2026-08-21T18:47:45.590591Z`.
- Wheel: `controlel-0.12.0-py3-none-any.whl`, 231,118 bytes, SHA-256
  `d8fd95c1534affd4f1c967e6765a8682587e05dc54528b86721332e950aaf78b`.
- Sdist: `controlel-0.12.0.tar.gz`, 160,765 bytes, SHA-256
  `6e59c5fae5098a35069458f5c09b2eed8e837cd9a95b7bd7156865a1acdde6a6`.
- Both public files match the final deterministic artifacts bound to the tag.
- Home Assistant integration 0.12.0 remains unpublished until its separate
  validation, review, tag, and GitHub/HACS release steps are complete.
