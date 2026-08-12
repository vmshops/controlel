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
-> OperatingModePolicy
-> SourceReconciliationPolicy
-> earliest eligibility/grace deadline scheduled
-> indeterminate grace: no command
   determinate: demand HeatSourceCommand
   indeterminate timed out: configured safety HeatSourceCommand
-> HeatSourceCommandDispatcher
-> HeatSourcePort
-> HeatSourceControlState after successful execution
-> HeatDemandEvaluationResult nested in RuntimeProcessingResult
```

Recovery and reported-source ingestion enter through explicit runtime methods
on the same serialized execution path. They reevaluate current demand and
source evidence; they do not replay a stored command or create a second control
loop.

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

The core has no production scheduler implementation. The first Home Assistant
host supplies a one-shot absolute-time scheduler adapter. There are no polling
loops, cleanup jobs, persistence, polling-based retries, modulation, DHW
behavior, valve control, source routing, multiple sources, or physical
confirmation.

## Reconciliation, recovery, and operating modes

External ownership produces diagnostics only. For Controlel-owned sources,
reported divergence is assessed against current desired command and the
existing source safety state. External-on/no-heat drift with unknown transition
age schedules a five-minute hold deadline. Expiry reevaluates current evidence;
if correction is still required, the command passes through minimum-time and
safety policy. Failed correction schedules one 30-second retry eligibility
deadline, while successful correction waits for new reported evidence. This is
deadline-driven retry semantics, not polling.

`begin_source_recovery()` opens a 30-second bounded evidence window.
`ingest_reported_source_state()` accepts explicit reported state without
turning it into command success or physical reality. Restart/reload does not
restore transition history. Stale reported evidence and stale scheduled
callbacks are rejected by timestamp and generation protection.

`NORMAL` preserves the ordinary demand path. `SAFE_HEATING` uses only configured
temperature evidence and can form a capability-gated `WATER_TARGET` intent;
physical water-target dispatch is not implemented. `EMERGENCY_OFF` uses the
existing safety-disable bypass. `MANUAL_RECOVERY_HEAT` is bounded to two hours
by default, and reload explicitly cancels it without recreating its deadline.

Every heat-demand result also enforces temporal coherence: the confirmation
assessment evaluation time must equal the building-demand evaluation time for
that current evaluation. Scheduled stale, grace, reconciliation, and
source-protection evaluations therefore refresh unchanged confirmation state
at the current aggregate evaluation time instead of reusing an older
assessment timestamp.

## Fatal runtime supervision and recovery

When the active normal runtime fails fatally, `RuntimeSupervisor` first revokes
NORMAL command authority and advances the runtime generation. It then stops
the quarantined runtime best-effort, transfers truthful source protection and
reported evidence, grants sole authority to `FailsafeRuntime`, and evaluates
either `SAFE_HEATING` from valid trusted temperature evidence or
`EMERGENCY_OFF` otherwise. The resulting action still passes through the
existing source-control safety and minimum-time policy before dispatch.

The supervisor schedules one restart attempt at the next fixed five-minute
eligibility boundary. A default campaign permits three attempts. Campaign and
generation tokens make early, cancelled, or stale callbacks inert, and
failsafe retains authority while a candidate normal runtime is constructed.
On success, the candidate receives an immutable handover of reported evidence,
ownership, capabilities, reconciliation state, and source-control protection
state before NORMAL authority is restored. Unknown evidence stays unknown;
successful dispatch or transition history is never invented.

## Serialized execution and shutdown

The Home Assistant host submits every public call and scheduled callback
through one dedicated single-worker executor. `ControlRuntime` additionally
acquires a non-blocking
execution guard for the entire flow above. It never waits or queues. Observer,
port, scheduler, or competing-thread re-entry raises
`RuntimeReentrancyError`; a compliant host avoids normal overlap.

`stop()` follows this exact order:

```text
enter guard
-> mark STOPPED
-> invalidate generation
-> capture handle
-> clear handle and deadline ownership
-> best-effort cancel
```

Repeated stop is a no-op. A direct stop that overlaps an operation is rejected;
the runtime does not wait. A compliant host submits stop after the active
operation. If a callback runs first, it completes or fails before shutdown. If
stop runs first, the callback is a no-op. No shutdown source command is
created, and stopped runtimes cannot restart.

Scheduled callback exceptions cannot produce a result. Exact ordinary
exceptions are reported to `ScheduledRuntimeFailureSink` after the guard is
released. Sink exceptions escape to the host callback boundary. Synchronous
public exceptions continue to propagate to their caller.

`Scheduler` tasks are one-shot aware absolute wall-clock deadlines. Callbacks
may be late, cancellation is best effort, and queued callbacks may arrive
after cancellation. A runtime-compatible Scheduler delivers callbacks on the
same serialized host context; generation checks remain authoritative.

## Home Assistant observation and startup flow

The adapter subscribes only to the configured temperature entity. It accepts
finite numeric Celsius and Fahrenheit states, converts Fahrenheit to Celsius,
and uses the aware `State.last_updated` exactly as
`Measurement.timestamp`. Unknown, unavailable, empty, malformed, non-finite,
missing-unit, unsupported-unit, missing-timestamp, and naive-timestamp states
produce no measurement. Receipt time, `SystemClock.now()`, and
`State.last_changed` are never timestamp fallbacks.

Startup subscribes in buffering mode before reading the current state. It
processes the snapshot, drains buffered state changes in arrival order, calls
`ControlRuntime.start()` on the runtime worker, drains events accumulated
during start, and atomically switches to live ordered submission. This ensures
valid initial evidence is processed before a zero-grace startup safety action
can be selected.

The `HeatSourcePort` maps typed enable and disable actions to two immutable
Home Assistant service calls. It waits on the runtime worker for blocking
service completion marshalled to the event loop. Normal completion records
applied core state but does not prove physical source state.
