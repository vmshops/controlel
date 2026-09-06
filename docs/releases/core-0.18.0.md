# Controlel Core 0.18.0

Status: prepared release candidate

Release: Controlel Core 0.18.0

## Summary

Core 0.18.0 packages mainline Core capabilities added after immutable public
Core 0.17.0 while preserving Heating and canonical configuration v3 behavior:

- module-scoped active-reference persistence and resolution contracts;
- Water shutoff output contracts and activation-ready optional notification,
  siren, and shutoff role lists;
- Water Safety evidence-store and snapshot persistence failures logged without
  blocking in-memory state transitions, fault deadlines, or independently
  isolated valve, siren, and notification attempts.

## Frozen release boundary

- Heating and canonical configuration v3 behavior remain unchanged from the
  current mainline at base `e1f2db5511c11949d8230fd0126b2705d2665249`.
- UNKNOWN and UNAVAILABLE sensor observations are not interpreted as dry.
- An accepted notification, siren, or valve request records a command outcome
  only; it does not confirm the physical output state.
- Water Safety adaptation, device-specific automation, and Heating redesign are
  outside this release.
- No Home Assistant manifest, release artifact, tag, publication, or dependency
  change is prepared here. The repository HA candidate remains a separate
  composition on published Core 0.17.0.

## Candidate validation and publication separation

- Python: 3.13 or newer.
- Runtime dependency remains only `pydantic>=2.0`.
- Candidate validation builds exactly one wheel and one sdist, checks their
  Water API contents and metadata, runs Twine validation, and imports the wheel
  from an isolated clean environment without Home Assistant installed.
- Candidate SHA-256 identities and the provenance manifest are generated only
  after the release-preparation commit so that they bind to that exact commit.
- The candidate is not published or tagged. Publication requires separate
  approval and a later annotated `core-v0.18.0` tag on the reviewed commit.
