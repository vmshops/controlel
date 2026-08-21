# Controlel Core 0.12.0

Status: candidate

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
- The immutable Core tag will be `core-v0.12.0` after final review.
- Build, clean-install, provenance, tag, and PyPI publication must complete
  before Home Assistant integration 0.12.0 may be published.
