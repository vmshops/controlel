# Controlel Core 0.11.0

Status: published

Release: Controlel Core 0.11.0

Summary
-------
M31C.1 — Heating Performance Assessment Foundation. This release provides a
passive observation and deterministic assessment foundation for heating
performance monitoring. It is passive/assessment-only and does not perform any
control feedback.

Highlights
----------
- Canonical passive heating performance monitoring and assessment APIs
- HeatingPerformanceAssessmentCriteria, -Type, -Status and related types
- ZoneHeatingPerformanceState and deterministic assessment identities
- JSON-safe diagnostics projection and bounded per-zone assessment state

Boundary and semantics
----------------------
- Passive assessment only: no control feedback path in Core 0.11.0
- No polling and no persistence are part of this release
- Explicit insufficient-evidence reporting is supported
- Target-change rebasing and episode isolation are present
- Duplicate/out-of-order timestamp handling and deterministic recovery confirmation
- Independent multi-zone assessment

Not included in this milestone
------------------------------
- M31C.2 anomaly transition policy (future work)
- M31C.3 UserActivity → notification projection (future work)

Distribution and release model
------------------------------
- Core releases are published on PyPI and are tag-bound (git tag `core-v0.11.0`).
- There is intentionally no GitHub Release for Core; release provenance is
  recorded by the repository's canonical build tooling and provenance manifest.

Compatibility
-------------
- Compatible HA integration version: 0.11.0 (note: the HA integration 0.11.0
  intentionally pins the public Core 0.10.0 via its manifest)

Provenance
----------
Canonical provenance and artifact records are produced by this repository's
packaging tooling. See release-metadata/releases.yaml (field 'tagged_at' records the git tag object timestamp) and dist/core-0.11.0-final
for provenance manifests (not all files are present in every clone).
