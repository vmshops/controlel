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
zone/source/correlation identity, an optional independent activity-lifecycle ID, previous/new state, requested command,
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

## M31B smart-notification foundation

M31B.2 makes `UserActivity` the sole production notification input. Technical
events are first composed into bounded human-meaningful activity revisions; the
application flow is strictly one way:

```text
OperationalEventStream -> UserActivityComposer -> UserActivityStream
                       -> NotificationPlanner -> NotificationProcessor
                       -> NotificationDeliveryPort
```

Event severity remains factual evidence. `UserActivityLevel` is the primary
attention classification, with `critical`, `operational`, `detailed`, and
`debug` levels. Every activity type has an explicit category and notifiable
lifecycle-stage rule. Fine-grained technical noise that does not compose into
an activity cannot produce a notification. The legacy event-level mapping is
retained only as a compatibility API and is not a production planner input:

| Notification level | Operational event codes |
| --- | --- |
| Critical | `runtime_fatal`, `safety_grace_expired`, `safety_disable_requested`, `emergency_disable_requested`, `restart_budget_exhausted` |
| Operational | `runtime_recovered`, `measurement_became_stale`, `measurement_became_unavailable`, `measurement_recovered`, `source_command_failed`, `corrective_action_dispatched`, `failsafe_entered`, `failsafe_exited`, `restart_attempt_failed` |
| Detailed | `runtime_started`, `runtime_stopped`, `heat_demand_started`, `heat_demand_confirmed`, `heat_demand_cancelled`, `heat_demand_satisfied`, `safety_grace_started`, `source_enable_requested`, `source_disable_requested`, `source_command_dispatched`, `source_command_deferred_minimum_on`, `source_command_deferred_minimum_off`, `reported_source_state_changed`, `source_drift_detected`, `source_reconciliation_started`, `source_reconciliation_completed`, `corrective_action_held`, `restart_attempt_started`, `command_authority_changed` |
| Debug | `measurement_became_valid` |

Activity policy is exhaustive at import and in tests. Policy produces
localization-neutral codes and allowlisted scalar parameters, never arbitrary
exception text or a claim about unobserved physical state.

Recipients have a stable logical ID, generic transport name and target,
enabled flag, minimum level, and optional category filter. Core does not
understand host-specific delivery schemas. Intent provenance identifies the
source activity, activity type, correlation, zones, sources, lifecycle stage,
and only allowlisted scalar evidence. De-duplication uses recipient, activity
identity, and material lifecycle stage/outcome. Ordinary intents use a
per-recipient/per-category sliding window
(default 10 per 60 seconds). CRITICAL intents use an independent emergency
anti-storm ceiling (default 20 per 60 seconds per recipient).

`NotificationProcessor` owns the activity-revision cursor. `UserActivityStream`
keeps unique-activity retention counters separate from its monotonic revision
sequence, so `OPEN` to terminal changes are observable without duplicating
history. Missing revision gaps and overflow occurrences are exact; policy
suppression and normalized delivery failure advance the cursor, while an
unexpected processing failure does not advance beyond the failed revision.

Notification history has its own bounded in-memory capacity (default 100) and
does not alter operational-event retention. Notification processing is
best-effort and memory-only. Outcomes are explicit: `delivered`, `failed`,
`suppressed_policy`, `suppressed_duplicate`, `rate_limited`, and
`no_recipient`. There is no retry loop, timer, polling, persistence,
notification-driven control, host adapter, or automatic recipient discovery in
the core boundary.

Home Assistant integration `0.10.0` composes the public core boundary without
reinterpreting it. A thin `NotificationDeliveryPort` adapter invokes only
explicitly configured `notify.<service>` targets on the HA event loop. Runtime
completion marks one shared drain dirty; an active drain task is reused and
loops only while new work was marked pending. This is event-driven coalescing,
not polling or a retry scheduler. Configuration and redacted diagnostics remain
adapter concerns, while mapping, recipient filtering, deduplication, cursor and
overflow semantics, and both rate limits remain application/core concerns.

Integration `0.10.1` adds only the HA presentation boundary: semantic title and
message codes are resolved through HA translations, interpolated from an explicit
safe scalar allowlist, and replaced by generic text on any rendering failure.
Event selection, policy, cursor, deduplication, and rate limiting remain unchanged.

M31C may consume operational events for statistics. Aggregation is not part of
M31A or M31B.

## M31B.1 user-activity foundation

M31B.1 introduces `UserActivity` as a separate immutable semantic layer:

```text
OperationalEvent = fine-grained technical evidence
UserActivity      = one human-meaningful occurrence
Notification      = a future selected UserActivity consumer
Decision Trace    = bounded internal decision evidence
```

`UserActivityComposer` passively consumes immutable operational-event snapshots
with its own cursor. It retains bounded in-memory lifecycle context and publishes
the latest immutable revision of bounded activities through `UserActivityStream`.
The snapshot reports exact source progress, missed-event gaps, overflow
occurrences, open lifecycle count, retained/dropped activity counts, and the
latest activity timestamp. Lost source evidence causes incomplete lifecycle
context to be discarded; no missing activity or continuity is fabricated.

Composition uses only explicit `activity_id` evidence. The operational recorder
allocates independent lifecycle IDs for source reconciliation campaigns,
measurement/safety incidents, and building heating episodes. Existing command
correlation, per-zone demand correlation, and supervision campaign correlation
retain their original meanings. Timestamp proximity is never a join rule.

Requested source action, successful dispatch outcome, reported controller state,
and physical heat remain distinct. `HEATING_STARTED` and `HEATING_STOPPED` mean
that source-permission commands were dispatched; they do not claim burner
operation. A reconciliation is completed as `SOURCE_STATE_CORRECTED` only after
explicit reported agreement, not merely after corrective command dispatch.

The foundation has no scheduler, polling, persistence, host dependency, command
port, or feedback into regulation. M31B.2 switches only the Core notification
consumer to this public activity boundary. A future Home Assistant `0.11.0`
adapter update is separate and is not implemented here. Reload/restart begins
new in-memory lifecycle state and never fabricates continuity.

Performance and anomaly assessment remain outside M31B.1. Insufficient
temperature rise, falling temperature, time-to-target, actuator response, water
temperature analysis, adaptive thresholds, and learning belong to M31C, which
may later provide canonical assessment evidence for activity presentation.

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
