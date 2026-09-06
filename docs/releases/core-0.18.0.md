# Controlel Core 0.18.0

Status: published

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
- Published HA 0.14.0 and the repository HA 0.14.1 candidate separately pin
  exact public Core 0.18.0.

## Published artifacts

- Python: 3.13 or newer.
- Runtime dependency remains only `pydantic>=2.0`.
- Release validation built exactly one wheel and one sdist, checked their
  Water API contents and metadata, runs Twine validation, and imports the wheel
  from an isolated clean environment without Home Assistant installed.
- Immutable annotated Core tag: `core-v0.18.0`, resolving to
  `5ad5eca46046460c711510fbb09011b7db13b924`.
- Wheel: `controlel-0.18.0-py3-none-any.whl`, 289,368 bytes, SHA-256
  `559da4af03743728dad0f0b141c3690f918fb84a670928f44881c06e600f092d`.
- Sdist: `controlel-0.18.0.tar.gz`, 205,854 bytes, SHA-256
  `3734bf32a509d3fdfc77689407d7b1f51dcd9d5182650b7115fbbc9224cb9b32`.
- Published PyPI bytes match the deterministic final artifacts bound to
  `core-v0.18.0`.
