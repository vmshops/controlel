# Domain Model

## Sensor and zone configuration

`SensorId` is stable observation identity and `ZoneId` is the logical regulated
subject. Each `Sensor` belongs to one zone. Every configured `Zone` has one
required `primary_sensor_id`, one strictly positive
`primary_measurement_max_age`, and one target temperature.

Every zone returned by `ZoneRepository.list_all()` participates in building
heat-demand arbitration. `Zone` inherits `Entity.enabled`, but enabled-state
semantics are deliberately not used in this milestone. Missing or ineligible
demand therefore remains uncertainty regardless of `enabled`.

## Observation provenance and decisions

`Measurement.timestamp` is copied exactly to `ControlContext.observed_at` and
then to `Decision.observed_at`. All three values identify the same source
observation and must be timezone-aware. `Decision.timestamp` remains the
independently generated decision-creation time and is never used for demand
freshness.

`DecisionAction` describes one zone's regulation intent. Its stable values
remain `enable_heating`, `disable_heating`, and `observe_only`.

## Source evidence and operating-mode contracts

`SourceOwnership` states whether reconciliation authority belongs to Controlel
or an external controller. `SourceCapabilities` is an immutable explicit set;
the current source contract always includes `ENABLE_DISABLE` and may advertise
`WATER_TARGET`. Capability is permission to form an intent, not proof that an
adapter dispatched it or that hardware applied it.

`ReportedSourceEvidence` contains one reported controller state and its exact
observation timestamp. An optional transition timestamp makes history known;
absence keeps transition history explicitly unknown. `ENABLED`, `DISABLED`,
`UNKNOWN`, and `UNAVAILABLE` describe only what the controller reported. They
never represent physical burner, flame, pump, or heat-output confirmation.

`OperatingMode` has stable values `NORMAL`, `SAFE_HEATING`, `EMERGENCY_OFF`,
and `MANUAL_RECOVERY_HEAT`. `SafeHeatingProfile` is immutable configuration,
while `SafeHeatingTemperatureEvidence` is observed input with explicit quality.
`WaterTargetIntent` is capability-gated requested intent and is deliberately
separate from command outcome and physical water temperature.

`CommandAuthority` explicitly identifies the sole source-command owner as
`NORMAL` or `FAILSAFE`. A fatal normal-runtime transition advances its
generation before failsafe authority is granted, so ports retained by the
quarantined generation cannot dispatch. `RestartPolicy` is a finite,
deterministic contract: the default campaign permits three attempts at a fixed
five-minute interval. Handover carries only known command, reported-state,
transition, ownership, capability, reconciliation, and protection evidence;
missing evidence remains unknown and no history is fabricated.

## Requested heating demand

An actionable decision maps to an immutable `ZoneDemand` containing:

- `ZoneId` of the requesting zone;
- a `requires_heat` boolean;
- the exact primary `SensorId` provenance;
- the exact observation time.

Demand is retained desired state, not a measurement, decision, executable
command, or successfully applied state. `OBSERVE_ONLY` creates no demand and
does not erase a previously retained demand.

`BuildingHeatDemand` is a timestamped, immutable aggregate with one stable
status: `heat_required`, `no_heat_required`, or `indeterminate`. It contains
ordered evidence for eligible demands and missing, expired, and future-dated
zones without copying `Measurement` objects.

Any eligible true demand means heat is required. No heat is required only when
every configured zone has an eligible false demand. Every other state is
indeterminate.

## Commands and applied state

`HeatSourceCommand` is the executable request for the one shared heat source.
It uses `CommandFamily.HEATING` and `HeatingAction`, but has no `ZoneId`,
synthetic building zone, or heat-source identifier.

`HeatSourceControlState` is singleton in-memory state for the latest
successfully applied shared-source action. It records the action, command ID,
and application time. It is not physical boiler confirmation.

`HeatDemandSafetyState` is separate application orchestration state. It records
the start of one uninterrupted indeterminate period, the last determinate
aggregate status for diagnostics, and the last evaluation time for
clock-regression detection. It is neither observed state, requested zone
demand, aggregate evidence, nor physical source state.

The existing zone-targeted `Command`, per-zone `ControlState`,
`ZoneActuatorRouter`, `CommandDispatcher`, and `ActuatorPort` remain a separate
zone-actuator path. They are not used by the shared-source `ControlRuntime`.

The safety policy requires a finite explicit grace `timedelta` and one explicit
typed timeout `HeatingAction`. Zero grace deliberately makes the timeout action
active immediately; there is no implicit action or indefinite mode.

There is no persistence, polling, background thread, production scheduler
adapter, modulation, DHW behavior, valve control, source routing,
multiple-source topology, or real hardware adapter.
