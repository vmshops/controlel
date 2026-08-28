# Controlel Core 0.16.0 candidate

Status: unreleased development candidate.

This Core boundary carries the canonical configuration v3 backend required by the
completed Configure flow, Setup Wizard, and Heating/Settings surfaces:

- schema v3 models with explicit field ownership, editability, and defaults;
- draft, validation, conversion-review, and activation lifecycle contracts;
- greenfield Heating authoring and deterministic v2-to-v3 migration; and
- reference binding and health checks without inferring physical state.

There is no runtime control algorithm, activation behavior change, or automatic
migration beyond explicit v2-to-v3 conversion in this candidate. Published Core
0.15.0 records and the Home Assistant integration manifest dependency pin remain
unchanged until separate publication work.
