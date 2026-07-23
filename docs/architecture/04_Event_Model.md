# Event Model

## Notification contract

`EventBus` remains a synchronous notification mechanism. It calls subscribers
in registration order, discards return values, and returns `None`. Functional
handlers are invoked explicitly by `ControlRuntime`, not subscribed to the
bus. Subscriber exceptions propagate unchanged.

Temperature handling occurs before `TemperatureMeasuredEvent` publication.
Every normal handler result publishes its exact temperature event, including
admission rejection, ordering rejection, secondary input, and ineligible
primary observations. A configuration exception interrupts processing before
normal notification, as before.

Every produced `DecisionCreatedEvent` is published before demand creation,
arbitration, or shared-source execution. The event contains the complete
`Decision`, including `SensorId`, `ZoneId`, and `observed_at`; it does not
duplicate those fields.

The event bus does not return decisions, demands, aggregates, commands, or
runtime results. No demand, aggregate, command-created, expiration, diagnostic,
or health event is introduced.

## Decision notification and execution separation

`DecisionAction` now explicitly represents zone heating-demand intent. After
decision publication, `ZoneDemandHandler` maps enable and disable intent to a
retained `ZoneDemand`; `OBSERVE_ONLY` maps to no demand and leaves existing
demand unchanged.

The shared-source runtime then derives `BuildingHeatDemand`. A determinate
aggregate creates a demand `HeatSourceCommand`. Indeterminate demand creates no
command during its finite grace period and creates the explicitly configured
safety command at or after the timeout boundary. Source execution is therefore
explicit orchestration and never depends on event subscriber ordering or
return values.

The existing `DecisionEventHandler` still maps decisions to zone-targeted
`Command` objects for the independent zone-actuator path. `ControlRuntime` does
not invoke that path for the shared source.

Decision publication remains observable even when source execution is later
suppressed or fails. If a decision observer raises, demand is not updated and
source processing does not begin. No result object is returned for observer,
configuration, clock, validation, or port exceptions.

## Synchronous processing results

Actionable measurement processing returns `RuntimeProcessingResult`. It keeps
the stable no-decision, observe-only, indeterminate, executed, and suppressed
statuses and adds explicit executed/suppressed safety-command statuses. Demand
evidence, safety assessment, command, trigger, and next deadline are carried by
one nested `HeatDemandEvaluationResult`; the runtime result retains the exact
originating `DecisionCreatedEvent`.

Startup, scheduled, and manual arbitration have no originating decision and
return `HeatDemandEvaluationResult` directly. A timer never fabricates a
`Measurement`, `SensorId`, `ZoneId`, `Decision`, or `DecisionCreatedEvent`.
No-decision and `OBSERVE_ONLY` paths do not evaluate demand or alter safety
state or scheduling.

Event-only observers do not receive this synchronous result. Logging,
persistence, correlation IDs, and diagnostic events remain outside scope.

## Observer execution ownership

Event publication executes inside the complete guarded runtime operation.
Subscribers therefore run on the authoritative serialized host context.
Subscriber configuration must be completed before processing or performed
through that same context.

If an observer synchronously calls `start()`, `process_temperature()`,
`reevaluate_heat_demand()`, or `stop()`, the nested call raises
`RuntimeReentrancyError` immediately before it can mutate runtime state.
Subscriber exceptions, including that error when uncaught, continue to
propagate through the synchronous public call.

Scheduled evaluation has no synchronous caller. Its ordinary exceptions are
reported through the mandatory `ScheduledRuntimeFailureSink`, not through a
notification event. The sink is invoked only after the runtime guard has been
released.
