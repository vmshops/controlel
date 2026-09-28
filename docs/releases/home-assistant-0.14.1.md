# Controlel Home Assistant integration 0.14.1

Status: published

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

## Published release boundary

The immutable integration tag is `v0.14.1`, resolving to
`0746c5cb0eced2350e1883f5f2cb5514040b9886`. The GitHub release includes the
installable `controlel.zip` HACS asset. HACS default-repository submission
remains external and is not default-store inclusion.

Version 0.14.2 is a separate, unpublished candidate.
