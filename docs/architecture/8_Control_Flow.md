# Control Flow

The shared-source synchronous flow is:

```text
Measurement
-> TemperatureMeasuredEvent
-> timestamp admission
-> RuntimeStateStore
-> primary-sensor freshness
-> ControlContext(sensor_id, zone_id, observed_at)
-> regulation
-> Decision(sensor_id, zone_id, observed_at, DecisionAction)
-> DecisionCreatedEvent notification
-> ZoneDemandHandler
-> ZoneDemandStore
-> HeatDemandAggregator(all configured zones, Clock)
-> BuildingHeatDemand
-> indeterminate: no command
   determinate: HeatSourceCommand(CommandFamily.HEATING, HeatingAction)
-> HeatSourceCommandDispatcher
-> HeatSourcePort
-> HeatSourceControlState after successful execution
-> RuntimeProcessingResult
```

`ControlRuntime` explicitly invokes every functional step. It requires one
`HeatSourcePort`; it no longer accepts actuator routes and does not construct
`DecisionEventHandler`, `ZoneActuatorRouter`, `CommandDispatcher`, or a
zone-targeted `Command`.

## Provenance

The exact effective `Measurement.timestamp` is copied through
`ControlContext.observed_at`, `Decision.observed_at`, and `ZoneDemand.observed_at`.
`Decision.timestamp` is independent creation time and has no freshness role.

## Arbitration

Every configured zone participates. Inherited `Entity.enabled` is intentionally
ignored. Missing, expired, and future-dated demand is unknown. Any eligible true
demand produces `HEAT_REQUIRED`; `NO_HEAT_REQUIRED` requires eligible false
demand from every zone; otherwise the result is `INDETERMINATE`.

`INDETERMINATE` creates no command, does not call the port, and does not change
applied source state. It may therefore preserve an already-enabled source. A
silent-sensor shutdown policy requires a separate milestone.

A fresh command candidate is created for each determinate evaluation. The
dispatcher, not aggregate change detection, suppresses an action already
successfully applied. This allows a later actionable evaluation to retry after
port failure.

Startup follows the same truth table:

- first false with another zone missing: indeterminate, no command;
- first true with another zone missing: enable candidate;
- all zones fresh false: disable candidate;
- one-zone first false: explicit disable candidate;
- no retained demand or source state: no implicit action.

## Normal no-action and failure behavior

Admission rejection, same-sensor ordering rejection, secondary measurement,
and missing, expired, or future primary state preserve existing typed
no-decision reasons and do not update demand. Configuration and observer
exceptions also prevent demand update. `OBSERVE_ONLY` returns
`decision_without_command` and retains demand.

Source failure occurs after demand update and decision publication. It leaves
applied source state unchanged and propagates unchanged, so no
`RuntimeProcessingResult` is returned. The next actionable evaluation can
retry.

The existing zone-actuator command, router, dispatcher, port, and per-zone
applied state remain independently usable but inactive in this shared-source
runtime.

There are no timers, cleanup jobs, persistence, automatic fail-safe commands,
scheduled retries, modulation, DHW behavior, valve control, source routing,
multiple sources, concurrency, or physical confirmation.
