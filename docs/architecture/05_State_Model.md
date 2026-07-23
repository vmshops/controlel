# State Model

## Latest measurement state

`RuntimeStateStore` remains the application-layer latest-observation store. It
holds at most one admitted `Measurement` per `SensorId`; equal timestamps use
arrival order and older same-sensor input is rejected. Historical measurements
remain a separate future concern.

Timestamp admission still occurs before storage using the required injected
`Clock` and runtime-wide `max_future_skew`. Primary measurement eligibility is
still:

```text
now - Zone.primary_measurement_max_age <= Measurement.timestamp <= now
```

Missing, expired, or future-dated primary observations create no decision.
They are not removed, and no fallback sensor or fail-safe action is introduced.

## Requested zone-demand state

`ZoneDemandStore` is separate in-memory desired state. It retains at most one
immutable `ZoneDemand` per `ZoneId`, preserves first-zone insertion order, and
exposes list snapshots. A new actionable decision replaces only its zone's
demand. The store does not evaluate freshness or remove expired entries.

Admission rejection, out-of-order input, secondary input, missing or ineligible
primary observations, configuration exceptions, and `OBSERVE_ONLY` do not
change retained zone demand.

Demand freshness uses `ZoneDemand.observed_at`, which is the exact originating
measurement timestamp. It never uses `Decision.timestamp`. During each
arbitration, `HeatDemandAggregator` reads `Clock.now()` once and classifies every
configured zone:

```text
missing demand                         -> unknown
observed_at < now - primary max age   -> expired / unknown
observed_at > now                     -> future-dated / unknown
cutoff <= observed_at <= now          -> eligible
```

Expired demands remain stored for diagnostics. A source-sensor mismatch raises
an explicit configuration/state exception rather than becoming unknown.

Eligibility is inclusive at the expiry boundary. For a demand observed at
`observed_at`, the exact boundary
`observed_at + primary_measurement_max_age` remains eligible; the first expired
instant and scheduled re-evaluation is one `datetime.resolution` microsecond
later. A future-dated retained demand is scheduled for activation exactly at
its `observed_at`.

## Building heat demand

Every zone in `ZoneRepository` participates, regardless of inherited
`Entity.enabled`. The tri-state truth table is:

| Evidence | Status |
|---|---|
| No configured zones | `INDETERMINATE` |
| Any eligible true demand | `HEAT_REQUIRED` |
| Every configured zone has eligible false demand | `NO_HEAT_REQUIRED` |
| Anything else | `INDETERMINATE` |

Missing, expired, and future demand is unknown, never implicit false. Thus an
eligible true overrides uncertainty, while disabling requires complete fresh
false evidence.

## Applied shared-source state

`HeatSourceStateStore` holds one latest immutable `HeatSourceControlState`.
`HeatSourceCommandDispatcher` suppresses an action only when the same action was
already successfully applied. It saves new state only after
`HeatSourcePort.execute()` returns normally.

If execution raises, updated requested demands and safety state remain stored,
the already-installed next deadline remains active, prior applied source state
is preserved, and the exact exception propagates. A later actionable decision,
manual evaluation, or already-justified eligibility deadline can retry because
failed execution was never recorded. There is no dedicated retry timer.

The existing per-zone `ControlState` and `StateRepository` remain the separate
zone-actuator applied-state model and are not reused for the shared source.

## Indeterminate safety orchestration state

`HeatDemandSafetyStateStore` holds one immutable
`HeatDemandSafetyState`. The policy truth table is:

| Aggregate and elapsed time | Phase | Command |
|---|---|---|
| `HEAT_REQUIRED` | determinate | enable heating |
| `NO_HEAT_REQUIRED` | determinate | disable heating |
| `INDETERMINATE` before `indeterminate_since + grace` | grace | none |
| `INDETERMINATE` at or after the timeout | timed out | configured timeout action |

A determinate result clears the period. Persistent uncertainty preserves its
original start. A scheduled callback that first discovers expiry uses its
requested deadline as that start, so callback lateness consumes rather than
extends grace. Equal evaluation times are allowed; an evaluated time earlier
than retained `last_evaluated_at` raises an explicit clock-regression error.

`ControlRuntime` owns one reschedulable earliest-deadline task. The desired
deadline is the minimum of the next demand activation/expiry and a pending
grace timeout. Replacement is installed before the old handle is cancelled,
and a generation token makes stale, cancelled, replaced, or duplicate
callbacks harmless. A premature callback changes no state and re-arms the same
deadline.

The evaluated safety state is saved and the next callback is installed before
any command is created or dispatched. Scheduling failure therefore preserves
the new safety state, retains an old trigger when replacement failed, prevents
a new source command, and propagates. Cancellation and source failures also
propagate.

All measurement, demand, safety, scheduled-task, and applied-source state is
lost on restart. `ControlRuntime.start()` must be called to protect against a
silent sensor before the first measurement. Startup with no demand begins
grace, or applies the explicit timeout action immediately when grace is zero.
Normal port return records application-level success, not physical heat-source
confirmation.

## Runtime ownership and terminal lifecycle

The host serializes all runtime calls. A defensive non-blocking, non-reentrant
guard covers reads and writes to `RuntimeStateStore`, `ZoneDemandStore`,
`HeatDemandSafetyStateStore`, `HeatSourceStateStore`, timer ownership, event
publication, and source execution. The guard never waits or queues. Concurrent
or nested entry raises `RuntimeReentrancyError`.

The private lifecycle is:

```text
OPEN -> STOPPED
```

Repeated `start()` remains a valid evaluation while open. `stop()` is terminal
and idempotent. It marks the runtime stopped, invalidates schedule generation,
and clears handle/deadline ownership before best-effort cancellation.
Cancellation failure propagates but cannot reopen the runtime. Start,
temperature processing, and manual evaluation after stop raise
`RuntimeStoppedError`.

Stale, duplicate, cancelled, and post-stop callbacks perform no evaluation,
state mutation, command, or failure report. If a valid scheduled operation
fails, its exact ordinary exception and requested deadline are delivered to
`ScheduledRuntimeFailureSink` after guard release. Synchronous failures still
propagate directly and never enter that sink.

All runtime and lifecycle state remains in memory and is lost when the process
or runtime instance is replaced.
