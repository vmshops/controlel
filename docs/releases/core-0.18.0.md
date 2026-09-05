# Controlel Core 0.18.0

Status: unpublished candidate.

This candidate adds module-scoped active-reference persistence/resolution and
Water shutoff output contracts added after immutable public Core 0.17.0.
Water evidence-store errors are logged without blocking incident processing or
valve, siren, and notification attempts. Output failures remain isolated;
accepted commands do not prove physical state. No automatic valve reopening
or Heating control redesign is included.

The minor increment follows the repository's feature-release convention.
Python remains >=3.13 and the only runtime dependency remains pydantic>=2.0.
HA 0.14.0 pins exactly controlel==0.18.0. The real public 0.17.0 wheel cannot
satisfy the current integration imports.

No tag, public wheel/sdist hash, or publication identity is assigned to this
candidate. Checked-out wheels and canonical HA test bundles are development
artifacts. Core publication must precede successful public-wheel compatibility
validation and the later HA release.

## Candidate validation

Validation on 2026-09-06 used the installed candidate wheel with Home Assistant
2026.7.3 on WSL/Linux. Core and packaging suites passed 1,021 tests on both
Windows and Linux. The HA adapter/framework suites passed 443 tests with one
intentional opt-in bundle-loader skip; the isolated bundle-loader test passed
separately. All 20 HA Water blocker regressions passed against the final
candidate wheel. Ruff, formatting, compile/AST, translation JSON, YAML, and
strict HACS/Core package validation passed.

An independently reported unload during SETUP_IN_PROGRESS could not be
reproduced: 42 unload/reload test functions expanded to 49 cases, and all six
runs passed (294 cases total) in normal, reverse and seeded shuffled order.
The original traceback was unavailable, so the original cause remains
undetermined; no assertion was suppressed or speculative lifecycle fix added.

The real public Core 0.17.0 wheel fails current HA imports, including
`active_reference_for_module`, `active_references_from_data`,
`ACTIVE_REFERENCES_KEY`, `MAX_SHUTOFF_VALVE_TARGETS` and
`SHUTOFF_VALVE_ROLE_PREFIX`. Its immutable artifact identities remain in the
[0.17.0 release notes](core-0.17.0.md).

Core 0.18.0 is intentionally not public. The required public-wheel release gate
therefore remains blocked. After Core publication, the exact public composition
must pass independently before HA release approval, alongside remote CI and
real HAOS acceptance checks.
