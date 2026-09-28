# Controlel Home Assistant integration 0.14.2

Status: published

## Summary

Integration 0.14.2 is the published Home Assistant release for the accepted
Water Safety P0 behavior. The published release commit is
`4adc942732e80ad7e90f341bce46fb1d36b12351`, tagged `v0.14.2`.

The accepted Water behavior/runtime checkpoint is
`574a22fabb6bb4b8999c42c10bc3c23b851af04a`. That checkpoint is not the
published release commit.

An unavailable optional Water notification output degrades non-fatally. That
condition no longer stops the whole Controlel config entry, and Heating
remained functional on the accepted real-home runtime. This release does not
solve notification reconciliation. It does not change Core. Core `0.18.0`
was not republished.

## Compatibility

- Required Core package: exactly `controlel==0.18.0` (existing public Core).
- Home Assistant: 2026.7.3 or newer.
- Config-entry version remains 1.

## Scope boundary

This release contains the already accepted Water Safety P0 behavior from
checkpoint `574a22fabb6bb4b8999c42c10bc3c23b851af04a`. It does not change Core,
Heating control behavior, configuration schema, or config-entry version.
test-HA runtime acceptance passed. Real-home runtime acceptance passed.
Reload and restart acceptance passed.

## Published release boundary

The immutable integration tag is `v0.14.2`, resolving to
`4adc942732e80ad7e90f341bce46fb1d36b12351`.

The GitHub release includes the installable `controlel.zip` HACS asset.
Verified SHA-256:
`c33c8d10032b867bb18474f22ba236ce347ae5049f941e6b1a8b49757bb35191`.

CONTROL-accepted release verification:

- exact release-candidate pull request CI passed;
- post-merge main CI passed;
- official HACS validation passed;
- hassfest passed, with the known non-blocking `CONFIG_SCHEMA` warning;
- public Core composition passed;
- the release asset was downloaded and its hash and content were verified;
- the release-triggered public-Core workflow passed.

HACS archive builds are not cross-platform byte-deterministic, because
checkout newline conversion can change working-tree bytes. The published
Linux asset is the verified artifact.
