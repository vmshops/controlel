# Controlel Home Assistant integration 0.14.1

Status: candidate

## Summary

Integration 0.14.1 prepares the published 0.14.0 runtime for HACS default
repository submission. It adds local brand assets, includes and verifies them
in the deterministic HACS archive, removes the temporary HACS `brands`
validation ignore, and updates current release documentation.

## Compatibility

- Required Core package: exactly `controlel==0.18.0`.
- Home Assistant: 2026.7.3 or newer.
- Config-entry version remains 1.

## Scope boundary

This patch changes distribution assets, validation, metadata, and documentation
only. It does not change Core, Home Assistant runtime behavior, configuration
schemas, persistence, migrations, heating or water behavior, frontend runtime
behavior, or source-control safety behavior.

## Candidate gate

Version 0.14.1 is not yet tagged, released, or published. HACS default
repository submission and any integration release require separate approval.
