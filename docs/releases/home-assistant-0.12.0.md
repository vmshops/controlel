# Controlel Home Assistant integration 0.12.0

Status: published

## Summary

Integration 0.12.0 pins `controlel==0.12.0` and adds a lazy host-facing Setup
backend over the Core setup authority. It supports read-only discovery,
recommendations, durable incomplete Heating drafts, resume, validation, and
non-active canonicalization. The read-only panel stack is introduced by the
separate integration 0.13.0 release boundary.

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

## Publication record

Core `controlel==0.12.0` and Home Assistant integration 0.12.0 are published
and immutable. The integration tag is `v0.12.0`, resolving to
`ae0b7368f2638bf8e9863eecb9f8fe5c016f7054`.
