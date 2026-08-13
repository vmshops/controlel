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

Event-only observers do not receive this synchronous result. The separate
operational-event recorder observes the completed semantic result; it never
participates in decision or command execution.

## M31A operational events

`OperationalEvent` is the canonical immutable record of a meaningful runtime
transition. Its stable schema contains a deterministic stream-local event ID,
aware timestamp, category, severity, event and summary codes, optional reason,
zone/source/correlation identity, previous/new state, requested command,
command outcome, and sorted JSON-safe scalar evidence. Arbitrary exception
messages are forbidden; normalized reason or exception-type codes are used.

The initial categories are `runtime`, `measurement`, `demand`, `safety`,
`source_control`, `source_resilience`, `supervision`, `heat_delivery`, and
`performance`. Semantic severity is one of `info`, `notice`, `warning`, or
`critical`; severity does not imply a notification preference.

`OperationalEventStream` retains at most 200 events per composed runtime. It
preserves emission order and reports total emitted, retained, and dropped
counts plus the latest evidence timestamp. Snapshots are immutable and their
projection is JSON-safe. Retention is memory-only: there is no database,
Recorder coupling, polling loop, or long-term history in M31A.

The transition-aware application recorder emits on condition entry, recovery,
command attempt/outcome, or lifecycle boundary. Repeated stable evaluations,
same-state source reports, snapshot refreshes, and one continuing protection
hold do not emit duplicates. Correlation IDs connect only evidence-backed
lifecycle relationships such as a command request/outcome, zone demand
confirmation, or fatal/failsafe/restart campaign. Reported source transitions
remain uncorrelated because the current adapter evidence has no explicit
causal token; matching direction or timing is insufficient.

The supervisor command-authority port records failsafe source request,
dispatch, and failure outcomes into the same stream used by normal runtime and
supervision lifecycle events. Recorder failure is contained outside source
execution. Each fatal generation supplies one deterministic supervision
correlation through failsafe entry, restart attempts, recovery, or exhaustion.

Operational events do not replace the decision trace. The trace explains each
bounded controller evaluation; operational events summarize meaningful
changes across evaluations. Observation, assessment, decision, requested
command, successful dispatch, reported controller state, and physical reality
remain distinct. A dispatch event never claims source operation, and a
reported enabled state never claims burner or heat output.

M31B may consume the immutable read boundary for notification policy and M31C
may consume it for statistics. Neither delivery nor aggregation is part of
M31A.

## Observer execution ownership

Event publication executes inside the complete guarded runtime operation.
Subscribers therefore run on the authoritative serialized host context.
Subscriber configuration must be completed before processing or performed
through that same context.

For the Home Assistant host, this context is the integration's dedicated
single runtime worker, not Home Assistant's event loop or general executor.
The configured `state_changed` callback only captures the new state and
buffers or queues it. A state change caused by a heat-source service call is
processed after the currently executing runtime operation and cannot
synchronously re-enter `ControlRuntime`.

If an observer synchronously calls `start()`, `process_temperature()`,
`reevaluate_heat_demand()`, or `stop()`, the nested call raises
`RuntimeReentrancyError` immediately before it can mutate runtime state.
Subscriber exceptions, including that error when uncaught, continue to
propagate through the synchronous public call.

Scheduled evaluation has no synchronous caller. Its ordinary exceptions are
reported through the mandatory `ScheduledRuntimeFailureSink`, not through a
notification event. The sink is invoked only after the runtime guard has been
released.
