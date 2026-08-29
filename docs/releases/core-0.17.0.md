# Controlel Core 0.17.0

Status: prepared release candidate

Release: Controlel Core 0.17.0

## Summary

Core 0.17.0 adds Water Safety V1 to the current mainline while preserving the
existing Heating runtime and canonical configuration v3 behavior:

- immutable host-neutral moisture observation, assessment, incident, and
  persisted-state contracts;
- an event-driven runtime with explicit state transitions, sensor-fault grace,
  deterministic one-shot deadlines, truthful output-command outcomes, and no
  hidden polling loop;
- Water Safety Setup schema v1 recommendation, validation, canonicalization,
  activation, discovery, persistence, and host-service contracts; and
- presentation-neutral diagnostics plus the read-only Frontend API v1 Water
  Safety projection.

## Frozen release boundary

- Heating and canonical configuration v3 behavior remain unchanged from the
  current mainline at base `698d5cbc271809a6339b081e0b368050a9daa80f`.
- UNKNOWN and UNAVAILABLE sensor observations are not interpreted as dry.
- An accepted notification or siren request records a command outcome only; it
  does not confirm the physical output state.
- Water Safety adaptation, device-specific automation, and Heating redesign are
  outside this release.
- No Home Assistant manifest, release artifact, tag, publication, or dependency
  change is prepared here. The repository HA candidate remains a separate
  composition on published Core 0.16.0.

## Candidate validation and publication separation

- Python: 3.13 or newer.
- Runtime dependency remains only `pydantic>=2.0`.
- Candidate validation builds exactly one wheel and one sdist, checks their
  Water API contents and metadata, runs Twine validation, and imports the wheel
  from an isolated clean environment without Home Assistant installed.
- Candidate SHA-256 identities and the provenance manifest are generated only
  after the release-preparation commit so that they bind to that exact commit.
- The candidate is not published or tagged. Publication requires separate
  approval and a later annotated `core-v0.17.0` tag on the reviewed commit.
