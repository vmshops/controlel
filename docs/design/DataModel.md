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
demand remains retained. Retry requires a later actionable evaluation.

The existing zone-targeted `Command`, `ActuatorPort`, `ZoneActuatorRouter`,
`CommandDispatcher`, `ControlState`, and `StateRepository` remain a separate
zone-actuator model and are not used by shared-source `ControlRuntime`.

## Runtime outcomes

Existing runtime status and no-decision values remain stable. The added
`building_heat_demand_indeterminate` status carries the exact decision event
and aggregate without a command. Command outcomes carry the exact determinate
aggregate and `HeatSourceCommand`; aggregate status and action must agree.

There is no persistence, timer, cleanup, scheduling, automatic shutdown,
modulation, DHW behavior, valve control, source routing, multiple-source model,
real integration, concurrency, or physical-state confirmation. Expiration is
noticed only during later arbitration, and indeterminate demand preserves the
last successfully applied source state.
