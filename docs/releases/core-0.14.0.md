# Controlel Core 0.14.0

Status: candidate

Release: Controlel Core 0.14.0

## Summary

Core 0.14.0 makes Heating setup schema v2 policy-complete. Canonical Heating
payloads now carry explicit configured diagnostic and notification policies,
including bounded notification recipients and rate/history settings.

## Heating schema-v2 policy contract

- `HeatingDiagnosticPolicy` records the configured diagnostic profile, bounded
  Debug duration semantics, and the profile to restore after Debug.
- `HeatingNotificationPolicy` records whether notifications are enabled,
  ordered recipients, ordinary and critical rate limits, and bounded history.
- `HeatingNotificationRecipient` keeps the configured transport target separate
  from its redaction-safe `target_configured` assessment.
- Recipient order remains meaningful and participates in canonical content and
  the semantic fingerprint. Set-like recipient categories normalize to unique,
  sorted values.
- Heating settings use typed `HeatingAction` values and reject source bindings
  that do not match the selected simple source-control contract.

## Canonicalization and activation boundary

Policy-less Heating schema-v1 revisions remain integrity-readable and may be
imported only as inactive drafts. Validation reports that they require explicit
recanonicalization, and canonicalization refuses to apply schema-v2 defaults
under an existing schema-v1 identity.

Canonicalization requires the current validator policy version. Activation
preparation and commit require a registered module contract and reject a
candidate whose schema version is not the supported version. These checks do
not infer runtime readiness or physical state.

## Frozen release boundary

- No legacy converter is implemented.
- No schema, activation, or runtime migration is implemented.
- No Home Assistant setup-write or frontend M1 work is included.
- No heating-control, heat-delivery, source-control, protection, or safety
  behavior is changed.
- Home Assistant integration version `0.12.0` remains unchanged.
- The Home Assistant dependency remains pinned to `controlel==0.12.0`.

## Compatibility and publication order

- Python: 3.13 or newer.
- Runtime dependency remains only `pydantic>=2.0`.
- The immutable Core tag will be `core-v0.14.0` after final review.
- Build, clean-install, provenance, tag, PyPI publication, and independent
  public-artifact verification must complete before a Home Assistant
  integration may pin Core 0.14.0.
