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
-> HeatDemandSafetyPolicy
-> HeatDemandSafetyStateStore
-> earliest eligibility/grace deadline scheduled
-> indeterminate grace: no command
   determinate: demand HeatSourceCommand
   indeterminate timed out: configured safety HeatSourceCommand
-> HeatSourceCommandDispatcher
-> HeatSourcePort
-> HeatSourceControlState after successful execution
-> HeatDemandEvaluationResult nested in RuntimeProcessingResult
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

`INDETERMINATE` creates no command during the required finite grace period and
does not infer disable from incomplete evidence. At the exact timeout boundary
the explicitly configured typed timeout action is active. Every later
evaluation in the same timed-out period creates a fresh candidate; an already
applied action is suppressed, while a previously failed action remains
retryable.

A fresh command candidate is created for each determinate evaluation. The
dispatcher, not aggregate change detection, suppresses an action already
successfully applied. This allows a later actionable evaluation to retry after
port failure.

`ControlRuntime` construction is side-effect free. Explicit `start()` evaluates
empty or retained demand, creates initial safety state, and schedules the
earliest deadline. Startup follows the same truth table:

- first false with another zone missing: indeterminate, no command;
- first true with another zone missing: enable candidate;
- all zones fresh false: disable candidate;
- one-zone first false: explicit disable candidate;
- no retained demand: indeterminate grace, or the explicit timeout action when
  grace is zero.

`reevaluate_heat_demand()` performs the same arbitration manually without
changing a `ZoneDemand`. Startup, manual, and timer paths return
`HeatDemandEvaluationResult` directly and create no synthetic decision.

## Deadline orchestration

Demand remains eligible through its exact expiry boundary. The runtime
schedules expiry one microsecond later, and schedules a future demand's
activation exactly at its observation time. One reschedulable task always
targets the earliest eligibility or grace deadline. Same-deadline evaluation
keeps the handle; changed deadlines install a replacement before cancelling
the previous handle.

Generation tokens make stale and duplicate callbacks no-ops. A premature
callback reads the injected clock defensively and re-arms without evaluation.
A late callback evaluates against actual current time but supplies its
requested deadline as the first-indeterminate hint. Backward completed
evaluation time raises rather than resetting or clamping safety state.

## Normal no-action and failure behavior

Admission rejection, same-sensor ordering rejection, secondary measurement,
and missing, expired, or future primary state preserve existing typed
no-decision reasons and do not update demand. Configuration and observer
exceptions also prevent demand update. `OBSERVE_ONLY` returns
`decision_without_command` and retains demand. These paths do not evaluate,
reset, or reschedule safety state.

Scheduling occurs after safety-state update but before command creation.
Scheduling failure prevents source execution and returns no result. Source
failure occurs after demand update, decision publication, safety update, and
successful scheduling. It leaves applied source state unchanged and propagates
unchanged. Retry requires a later actionable or manual evaluation, or another
already-justified eligibility transition; there is no automatic retry poll.

The existing zone-actuator command, router, dispatcher, port, and per-zone
applied state remain independently usable but inactive in this shared-source
runtime.

There is no production scheduler implementation. There are no polling loops,
background threads, cleanup jobs, persistence, recurring retries, modulation,
DHW behavior, valve control, source routing, multiple sources, or physical
confirmation.
