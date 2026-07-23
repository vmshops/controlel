# Controlel Data Model

Version: 0.1

Status: Draft

## Configuration

`SensorId` resolves to a configured `Sensor`, whose `ZoneId` resolves to one
configured `Zone`. The zone supplies target temperature, required primary
sensor identity, and required positive `primary_measurement_max_age`.

All zones in `ZoneRepository` participate in building arbitration. Although
`Zone` inherits `Entity.enabled`, enabled state is not a participation filter in
this milestone.

## Observation and regulation

`Measurement` contains only `sensor_id`, observed temperature, and a
timezone-aware observation timestamp. Timestamp admission and same-sensor
ordering happen before regulation. Latest observations remain in
`RuntimeStateStore`; they are not history.

The selected primary measurement supplies `ControlContext.observed_at`.
Regulation copies it exactly to `Decision.observed_at`. `Decision.timestamp`
remains independently generated decision-creation time.

`DecisionAction` is zone demand intent. Its stable JSON values remain
`enable_heating`, `disable_heating`, and `observe_only`.

## Demand

An immutable `ZoneDemand` contains `zone_id`, `requires_heat`, exact source
`sensor_id`, and exact observation time. `ZoneDemandStore` retains one current
requested demand per zone without freshness evaluation or deletion.

`HeatDemandAggregator` classifies each configured zone at one injected clock
time. A demand is eligible at the inclusive boundary:

```text
now - zone.primary_measurement_max_age <= demand.observed_at <= now
```

Missing, expired, and future-dated demands are unknown. The immutable
`BuildingHeatDemand` carries ordered evidence and one stable status:

```text
any eligible true                         -> heat_required
all configured zones eligible false       -> no_heat_required
all other cases                           -> indeterminate
```

No `requires_heat` boolean is added to the aggregate because it would hide
indeterminate state.

## Shared-source execution

`HeatSourceCommand` contains UUID identity, timezone-aware creation time,
`CommandFamily.HEATING`, and typed `HeatingAction`. It has no `ZoneId` or
heat-source identifier. The single explicitly injected `HeatSourcePort` is the
shared-source execution boundary.

`HeatSourceControlState` contains the latest successfully applied source
action, command ID, and application time. `HeatSourceStateStore` retains one
such state. Identical applied actions are suppressed; different or missing
state permits execution. State changes only after normal port return.

Port failure preserves prior applied state while the newly requested zone
demand and evaluated safety state remain retained. Retry requires a later
actionable/manual evaluation or an already-justified deadline; no dedicated
retry timer exists.

The existing zone-targeted `Command`, `ActuatorPort`, `ZoneActuatorRouter`,
`CommandDispatcher`, `ControlState`, and `StateRepository` remain a separate
zone-actuator model and are not used by shared-source `ControlRuntime`.

## Runtime outcomes

`HeatDemandSafetyState` separately retains one uninterrupted indeterminate
period, the last determinate status, and the last evaluated time. A required
finite grace period and required explicit timeout `HeatingAction` produce:

```text
determinate heat required       -> enable demand command
determinate no heat required    -> disable demand command
indeterminate before timeout    -> no command
indeterminate at/after timeout  -> configured safety command
```

Zero grace is explicit immediate timeout behavior; there is no default or
indefinite mode. Exact demand expiry remains inclusive, so re-evaluation is
scheduled at expiry plus one microsecond. Future demand activates exactly at
its observation time.

`HeatDemandEvaluationResult` contains trigger, aggregate, safety assessment,
command, scheduled origin, and next deadline. Actionable processing nests it in
`RuntimeProcessingResult`; startup, scheduled, and manual evaluation return it
directly without a synthetic decision.

The runtime owns one reschedulable earliest-deadline handle guarded by a
generation token. Constructor creation has no side effects; explicit `start()`
establishes protection before a first measurement. Scheduler installation
precedes command creation, so scheduling failure prevents a new source action.
Late callbacks consume grace from their requested deadline, and completed
backward-time evaluation raises explicitly.

All in-memory measurement, demand, safety, schedule, and applied state is lost
on restart. There is no production scheduler adapter, polling, background
thread, persistence, recurring retry, modulation, DHW behavior, valve control,
source routing, multiple-source model, real integration, or physical-state
confirmation.
