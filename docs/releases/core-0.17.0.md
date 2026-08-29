# Controlel Core 0.17.0

Status: published

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

## Public artifact identities

- Immutable annotated Core tag: `core-v0.17.0`, resolving to
  `6f9c34498ab09e6fc212d18b507c35c003bf1479`.
- Wheel: `controlel-0.17.0-py3-none-any.whl`, 287,747 bytes, SHA-256
  `d818dd403b2aada29061662464ce9c0e3d37a5eea5d9059a1e3780cf13ffd3b6`.
- Sdist: `controlel-0.17.0.tar.gz`, 203,980 bytes, SHA-256
  `9020487dd1325ff58ec3ac0e9e3541a78840eaaae803b05f9613f28525bd41bd`.
- Both public files match the deterministic final artifacts bound to
  `core-v0.17.0`.

## Compatibility

- Python: 3.13 or newer.
- Runtime dependency remains only `pydantic>=2.0`.
- Home Assistant integration 0.14.0 pins exactly `controlel==0.17.0`.
