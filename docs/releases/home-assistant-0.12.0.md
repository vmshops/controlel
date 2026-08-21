# Controlel Home Assistant integration 0.12.0

Status: candidate

## Summary

Integration 0.12.0 pins `controlel==0.12.0` and adds a lazy host-facing Setup
backend over the Core setup authority. It supports read-only discovery,
recommendations, durable incomplete Heating drafts, resume, validation, and
non-active canonicalization. No frontend UI or frontend transport is included.

## Compatibility

- Required Core package: exactly `controlel==0.12.0`.
- Config-entry version remains 1.
- Existing installations retain the legacy runtime/configuration path and do
  not require an automatic migration for this release.
- Legacy settings are reported explicitly to Setup and are never silently
  merged into canonical configuration.

## Safety boundary

The Setup service has no runtime activation operation. Creating, editing,
validating, or canonicalizing a draft cannot change active control. A future
release must separately review activation and migration before exposing them.

## Publication gate

Do not tag or publish integration 0.12.0 until Core 0.12.0 is available from
PyPI, its immutable wheel/sdist provenance is recorded, and HA framework tests
have been rerun against that public package rather than the local candidate.

