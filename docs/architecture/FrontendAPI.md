# Frontend API v1

Status: Architecture design (no implementation)

This document defines the first stable contract between a future Controlel
frontend and the Controlel backend. It is a boundary definition only: no
endpoints, no frontend code, and no backend code are introduced by this
document.

## 1. Purpose

Controlel's control logic lives in a pure, deterministic, vendor-independent
core plus an application layer that owns orchestration, state stores, and
projections. A future UI must be able to display system status, heating
state, diagnostics, and setup readiness without depending on any of those
internal types.

The frontend needs a stable API boundary because:

- Core and application-layer types evolve with milestones. Internal names,
  enums, and snapshot shapes are implementation details, not a public
  contract. A UI bound to them would break on every internal refactor.
- The UI must show *what the system concluded*, not *how it concluded it*.
  The boundary forces every value the UI can show to be an explicit,
  explainable projection with a stable code.
- Safety semantics must survive the boundary. The distinction between
  requested command, dispatch outcome, reported state, and physical state
  is a core safety rule. A stable contract makes it impossible for a UI to
  accidentally present a command as a physical confirmation.
- One contract serves all future hosts. The same DTOs can be rendered by a
  Home Assistant panel, a web UI, or a mobile client without each client
  re-deriving meaning from raw entities.

The UI must not access Core directly because:

- Core exposes domain types (`Zone`, `Measurement`, `Decision`,
  `BuildingHeatDemand`, `HeatSourceControlState`, ...), not presentation
  data. It has no notion of labels, localization, or UI state.
- Core state is in-memory, per-runtime, and reconstructed on reload. It is
  not a stable read surface.
- Direct access would merge the command/observation/assessment/decision
  layers in the UI, which the architecture explicitly forbids.
- The application layer already owns the projections (bounded event
  streams, JSON-safe diagnostics, operational summaries). The frontend API
  reuses that discipline instead of bypassing it.

## 2. Architecture boundary

```text
Frontend UI
    ↓  (renders DTOs only; no knowledge of Core types)
Frontend API / DTO contract   ← this document (frontend_api_version = 1)
    ↓  (projects application state into DTOs)
Home Assistant adapter
    ↓  (host integration: config entry, entities, services)
Controlel application layer
    ↓  (orchestration, state stores, projections)
Core
```

Rules for the boundary:

- Dependencies point downward only. The DTO contract depends on nothing;
  the adapter projects application state into it.
- The DTO contract is the only surface a UI may depend on. UI code must not
  import, name, or pattern-match on Core or application-layer types.
- The contract is read-only in v1. It exposes observations, assessments,
  and setup state. It does not expose commands. Issuing control commands
  remains an explicit, separately designed operation (see Non-goals).
- Every DTO is a JSON-safe immutable projection: scalar fields, stable
  codes, bounded lists, no raw history, no arbitrary exception text. This
  matches the existing projection discipline (for example
  `SourceResilienceDiagnosticsV1`).
- The adapter is the only component that knows Home Assistant locators
  (`entity_id`). Locators never appear in DTOs as identity.

## 3. Initial API domains

v1 defines four read-only domains. Each domain is one response shape with
its own stable field set.

### 3.1 Overview

Purpose: answer "is the system alive, what mode is it in, and does anything
need attention?" without requiring the user to open a specific module.

Fields:

- `system.status` — runtime availability: `active`, `degraded`, `stopped`.
- `system.operating_mode` — stable mode code: `NORMAL`, `SAFE_HEATING`,
  `EMERGENCY_OFF`, `MANUAL_RECOVERY_HEAT`.
- `system.operating_mode_reason` — stable reason code, or `null`.
- `system.operating_mode_since` — timestamp, or `null` when unknown.
- `modules[]` — one entry per known module: `module_id`, `status`
  (`active`, `inactive`, `error`), `reason` (stable code or `null`).
  Heating is the first module; the list is open for future modules.
- `attention[]` — bounded list of items needing user attention:
  `attention_id`, `severity` (`info`, `notice`, `warning`, `critical`),
  `code` (stable reason code), `scope` (what it concerns), `summary`
  (localization-neutral label suggestion), `first_seen_at`.

Attention items are projections of existing evidence (operational events,
reconciliation state, validation results). The Overview domain never
introduces new physical claims.

### 3.2 Heating

Purpose: show what the heating system currently concludes, per zone and for
the shared heat source, with the reasoning available.

Building level (one shared heat source):

- `building.demand_status` — `heat_required`, `no_heat_required`, or
  `indeterminate`. This is the aggregate demand conclusion, not a physical
  state.
- `building.demand_reason_code` — stable code explaining the aggregate.
- `building.heat_source.permission` — the requested heat-source permission:
  `enabled`, `disabled`, or `unknown`. This is what Controlel requested,
  not what the boiler is doing.
- `building.heat_source.requested_command` — `enable`, `disable`, or
  `null` (no command requested).
- `building.heat_source.command_outcome` — `dispatched`, `failed`,
  `suppressed`, or `null`. A successful dispatch proves only that an
  adapter call returned successfully.
- `building.heat_source.reported_state` — what the controller reported:
  `ENABLED`, `DISABLED`, `UNKNOWN`, `UNAVAILABLE`.
- `building.heat_source.physical_state` — always `unknown` in v1 unless a
  future adapter supplies explicit physical evidence. Never inferred.
- `building.last_decision_summary` — the latest decision that influenced
  the current state: `decision_id`, `action`, `observed_at`,
  `reason_code`, or `null` when no decision exists yet.

Zone level (one entry per configured zone, ordered by stable `zone_id`):

- `zone_id` — stable zone identity (never an `entity_id`).
- `name` — display name; presentation only, never identity.
- `current_temperature_c` — latest admitted primary measurement, or `null`
  when missing.
- `measurement_state` — `fresh`, `expired`, `future_dated`, or `missing`.
- `measurement_age_seconds` — age of the latest measurement, or `null`.
- `target_temperature_c` — configured zone target.
- `demand_state` — `heat_required`, `no_heat_required`, or `indeterminate`
  for this zone's retained demand.
- `demand_reason_code` — stable code for the zone's latest decision, or
  `null`.
- `last_decision` — `decision_id`, `action` (`enable_heating`,
  `disable_heating`, `observe_only`), `observed_at`, `reason_code`, or
  `null` when the zone has produced no decision.

The Heating domain reports conclusions and evidence. It does not expose
hysteresis internals, raw measurement streams, or actuator positions.

### 3.3 Diagnostics

Purpose: explain what happened and why, for troubleshooting and trust.

Fields:

- `health.runtime_status` — `active`, `degraded`, `stopped`.
- `health.operating_mode` — same stable mode codes as Overview.
- `health.event_stream` — `total_emitted`, `retained`, `dropped` counts
  from the bounded operational event stream.
- `recent_events[]` — bounded, newest-first projection of operational
  events: `event_id`, `timestamp`, `category`, `severity`, `event_code`,
  `summary_code`, `reason_code` (or `null`), `scope`, optional
  `previous_state` / `new_state`, optional `command`
  (`action`, `outcome`). No arbitrary exception text; normalized codes
  only.
- `decision_trace` — summary of the latest decision chain:
  `decision_id`, `zone_id`, `sensor_id`, `action`, `observed_at`,
  `reason_code`, and a bounded `evidence[]` list of
  `{ code, value }` pairs (for example `measurement`, `target`,
  `threshold`). Plus `retained_count` and `total_decisions`.

Diagnostics is read-only evidence. It never triggers re-evaluation,
replay, or any control behavior.

### 3.4 Setup

Purpose: tell the user whether the system is ready to control, what is
missing, and why validation failed.

Fields:

- `readiness.state` — `ready`, `incomplete`, `invalid`, or `unknown`.
- `readiness.reason_code` — stable code, or `null` when `ready`.
- `missing_configuration[]` — bounded list: `code` (stable, for example
  `zone_primary_sensor_missing`, `heat_source_binding_missing`), `scope`
  (`module`, `zone`, `sensor`, `source`), `severity` (`error`, `warning`).
- `validation_messages[]` — bounded list: `code`, `severity`, `scope`,
  `summary` (label suggestion).

Setup state reflects the existing setup lifecycle (discovery, draft,
validation, activation). The Setup domain is read-only: it reports
readiness and validation results. It does not create drafts, activate
revisions, or mutate configuration.

## 4. Data principles

These principles apply to every domain and every future version.

1. **Normalized data, not raw Home Assistant entities.** The UI receives
   Controlel's normalized conclusions. `entity_id` values are adapter
   locators that Home Assistant may rename; they are never identity in a
   DTO and are not exposed as such.

2. **Stable IDs.** Identity is carried by stable identifiers: `zone_id`,
   `sensor_id`, `module_id`, `decision_id`, `event_id`, `attention_id`.
   IDs are opaque strings to the UI. Display names are separate and may
   change without breaking the contract.

3. **Localization-neutral codes.** All machine-readable values are stable
   `snake_case` codes (for example `heat_required`,
  `above_enable_threshold`, `source_report_drift`). Codes are defined once
   and never translated. A code's meaning is part of the contract.

4. **Labels are separate from machine values.** Human-readable text is
   carried in dedicated `summary` / `name` / `label` fields as a
   *suggestion*. The UI may ignore it and substitute its own translations.
   Code and label never share a field.

5. **Command state is not physical confirmation.** DTOs keep these facts
   separate and never merge them:
   - requested command (`requested_command`),
   - dispatch outcome (`command_outcome`),
   - reported controller state (`reported_state`),
   - physical state (`physical_state`).
   A `dispatched` outcome means the adapter call succeeded. It does not
   mean a valve moved, a burner lit, or heat was delivered.

6. **Unknown stays unknown.** Missing evidence is represented explicitly:
   `null` for absent values, `unknown` / `indeterminate` / `missing` codes
   for states. Unknown is never coerced to `false`, `disabled`, `0`, or
   any other concrete value. `UNKNOWN` and `UNAVAILABLE` reports remain
   distinct from `DISABLED`.

7. **Bounded and explainable.** Lists are bounded (retention counts are
   reported alongside). Every non-trivial state carries a stable reason
   code. No arbitrary exception text, tracebacks, or unbounded history
   crosses the boundary.

## 5. Versioning

Every response carries:

```json
"frontend_api_version": 1
```

### Compatibility expectations (within version 1)

- Additive changes are non-breaking: new optional fields, new list entries,
  new stable codes, new domains.
- Clients must tolerate unknown fields and unknown codes. An unknown code
  is rendered as "unknown" (or hidden), never guessed.
- Field semantics, once published, do not change within the same version.
- Bounded lists may change their retention size; clients must not assume a
  fixed length.

### Breaking change rules

A change is breaking and requires a new major version (`frontend_api_version
= 2`) when it:

- removes or renames a published field;
- changes a field's type or meaning;
- changes the meaning of a published code;
- changes the identity rules (for example what `zone_id` refers to);
- changes safety-relevant semantics (for example merging command outcome
  and reported state into one field).

Rules for major version transitions:

- The previous major version remains available for at least one full
  release cycle before removal.
- Clients declare the version they consume; the backend serves the
  requested version when available.
- Version negotiation is explicit. There is no silent behavior change
  under an unchanged version number.

## 6. Example DTOs

The examples below are illustrative shapes for `frontend_api_version = 1`.
They use the stable codes defined in this document. Timestamps are
timezone-aware ISO 8601.

### 6.1 Overview response

```json
{
  "frontend_api_version": 1,
  "generated_at": "2026-08-22T14:03:11+02:00",
  "system": {
    "status": "active",
    "operating_mode": "NORMAL",
    "operating_mode_reason": null,
    "operating_mode_since": "2026-08-22T06:12:40+02:00"
  },
  "modules": [
    {
      "module_id": "heating",
      "status": "active",
      "reason": null
    }
  ],
  "attention": [
    {
      "attention_id": "att-2026-08-22-0001",
      "severity": "warning",
      "code": "source_report_drift",
      "scope": { "type": "source" },
      "summary": "Heat source reports enabled while no heat is required",
      "first_seen_at": "2026-08-22T13:58:02+02:00"
    }
  ]
}
```

### 6.2 Heating response

```json
{
  "frontend_api_version": 1,
  "generated_at": "2026-08-22T14:03:11+02:00",
  "building": {
    "demand_status": "heat_required",
    "demand_reason_code": "zone_demand_confirmed",
    "heat_source": {
      "permission": "enabled",
      "requested_command": "enable",
      "command_outcome": "dispatched",
      "reported_state": "ENABLED",
      "physical_state": "unknown",
      "last_decision_summary": {
        "decision_id": "dec-2026-08-22-0031",
        "action": "enable_heating",
        "observed_at": "2026-08-22T14:02:58+02:00",
        "reason_code": "above_enable_threshold"
      }
    }
  },
  "zones": [
    {
      "zone_id": "zone-living-room",
      "name": "Living room",
      "current_temperature_c": 21.4,
      "measurement_state": "fresh",
      "measurement_age_seconds": 42,
      "target_temperature_c": 22.0,
      "demand_state": "heat_required",
      "demand_reason_code": "above_enable_threshold",
      "last_decision": {
        "decision_id": "dec-2026-08-22-0031",
        "action": "enable_heating",
        "observed_at": "2026-08-22T14:02:58+02:00",
        "reason_code": "above_enable_threshold"
      }
    },
    {
      "zone_id": "zone-bathroom",
      "name": "Bathroom",
      "current_temperature_c": null,
      "measurement_state": "missing",
      "measurement_age_seconds": null,
      "target_temperature_c": 23.0,
      "demand_state": "indeterminate",
      "demand_reason_code": null,
      "last_decision": null
    }
  ]
}
```

Note the two zones: one with fresh evidence and a confirmed demand, one
with missing evidence. The second zone is `indeterminate`, not
`no_heat_required`. Unknown stays unknown.

### 6.3 Diagnostics response

```json
{
  "frontend_api_version": 1,
  "generated_at": "2026-08-22T14:03:11+02:00",
  "health": {
    "runtime_status": "active",
    "operating_mode": "NORMAL",
    "event_stream": {
      "total_emitted": 148,
      "retained": 148,
      "dropped": 0
    }
  },
  "recent_events": [
    {
      "event_id": "evt-000148",
      "timestamp": "2026-08-22T14:02:59+02:00",
      "category": "source_control",
      "severity": "info",
      "event_code": "source_command_dispatched",
      "summary_code": "source_permission_enabled",
      "reason_code": null,
      "scope": { "type": "source" },
      "previous_state": "DISABLED",
      "new_state": "ENABLED",
      "command": { "action": "enable", "outcome": "dispatched" }
    },
    {
      "event_id": "evt-000147",
      "timestamp": "2026-08-22T14:02:58+02:00",
      "category": "demand",
      "severity": "info",
      "event_code": "zone_demand_confirmed",
      "summary_code": "zone_heat_required",
      "reason_code": "above_enable_threshold",
      "scope": { "type": "zone", "zone_id": "zone-living-room" },
      "previous_state": null,
      "new_state": "heat_required",
      "command": null
    }
  ],
  "decision_trace": {
    "decision_id": "dec-2026-08-22-0031",
    "zone_id": "zone-living-room",
    "sensor_id": "sensor-living-room-temp",
    "action": "enable_heating",
    "observed_at": "2026-08-22T14:02:58+02:00",
    "reason_code": "above_enable_threshold",
    "evidence": [
      { "code": "measurement", "value": "21.4" },
      { "code": "target", "value": "22.0" },
      { "code": "enable_threshold", "value": "21.5" }
    ],
    "retained_count": 20,
    "total_decisions": 31
  }
}
```

### 6.4 Setup response

```json
{
  "frontend_api_version": 1,
  "generated_at": "2026-08-22T14:03:11+02:00",
  "readiness": {
    "state": "incomplete",
    "reason_code": "zone_primary_sensor_missing"
  },
  "missing_configuration": [
    {
      "code": "zone_primary_sensor_missing",
      "scope": { "type": "zone", "zone_id": "zone-bathroom" },
      "severity": "error"
    }
  ],
  "validation_messages": [
    {
      "code": "sensor_max_age_too_large",
      "severity": "warning",
      "scope": { "type": "sensor", "sensor_id": "sensor-bathroom-temp" },
      "summary": "Primary measurement max age exceeds recommended bound"
    }
  ]
}
```

## 7. Non-goals for v1

- No command or write operations. The v1 contract is read-only. Issuing
  control commands, changing targets, or activating configuration remains
  a separate, explicitly designed operation with its own safety review.
- No raw entity access, no `entity_id` identity, no raw measurement
  streams.
- No actuator positions, valve states, or water-temperature values. These
  are not yet observable facts in the system and must not be invented.
- No physical-state claims. `physical_state` is `unknown` until explicit
  evidence exists.
- No unbounded history. All lists are bounded; retention counts are
  reported.
- No new control behavior. The contract projects existing state; it does
  not add state, timers, or feedback paths.
