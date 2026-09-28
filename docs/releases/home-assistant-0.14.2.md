# Controlel Home Assistant integration 0.14.2

Status: candidate

## Summary

Integration 0.14.2 is the unpublished release-closure candidate for the
accepted Water Safety P0 hotfix. The candidate checkpoint is
`574a22fabb6bb4b8999c42c10bc3c23b851af04a`.

Missing notification outputs degrade non-fatally instead of killing the whole
Controlel config entry. Heating remained functional on the accepted real-home
runtime. This candidate does not change Core.

## Compatibility

- Required Core package: exactly `controlel==0.18.0`.
- Home Assistant: 2026.7.3 or newer.
- Config-entry version remains 1.

## Scope boundary

This candidate contains the already accepted Water Safety P0 behavior from
checkpoint `574a22fabb6bb4b8999c42c10bc3c23b851af04a`. It does not change Core,
Heating control behavior, configuration schema, or config-entry version.
test-HA runtime acceptance passed. Real-home runtime acceptance passed.

## Candidate gate

Version 0.14.2 is not yet tagged, released, or published. Publication requires
separate CONTROL authorization.
