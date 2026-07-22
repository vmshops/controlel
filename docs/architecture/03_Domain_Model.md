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

The existing zone-targeted `Command`, per-zone `ControlState`,
`ZoneActuatorRouter`, `CommandDispatcher`, and `ActuatorPort` remain a separate
zone-actuator path. They are not used by the shared-source `ControlRuntime`.

There is no persistence, timer, scheduling, modulation, DHW behavior, valve
control, source routing, multiple-source topology, or real hardware adapter.
