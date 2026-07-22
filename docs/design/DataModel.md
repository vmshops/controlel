# Controlel Data Model

Version:
0.1

Status:
Draft


# 1. Purpose


# 2. Core Entities


# 3. Entity Relationships


# 4. Configuration Model

Configuration supplies target values and other regulation inputs. Target
temperature is not an observed measurement and is not stored in runtime
measurement state.

`SensorId` resolves to a configured `Sensor`, whose required `ZoneId` identifies
exactly one configured `Zone`. `Zone.target_temperature` is a typed
`Temperature` and is the source used to prepare `ControlContext`.

Every zone also requires `primary_sensor_id` and a strictly positive
`primary_measurement_max_age` `timedelta` with no default. The sensor identifier
selects its sole regulation input sensor but does not replace `Sensor.zone_id`,
which remains the only sensor-to-zone association. The configured primary
sensor must exist and must belong to that zone. The maximum age defines the
inclusive elapsed-time freshness boundary for the primary observation.

`SensorId` is observation provenance, while `ZoneId` is the logical regulated
subject. `ControlContext` and `Decision` carry both. `DecisionCreatedEvent`
preserves the complete decision without duplicating the identifiers, and an
executable `Command` carries only `ZoneId` as its logical target. Sensor
provenance is not currently command execution data.

Zone configuration contains no latest measurement or applied heating state.
Scheduling, persistence, disabled-state semantics, actuator routing and
configuration mutation are intentionally absent.

`ZoneId` is not a physical actuator identifier. Commands for every zone still
use one injected `ActuatorPort`; no zone-to-actuator routing exists. Multiple
sensors in one zone may produce repeated or conflicting commands. Future
durable causal tracing should introduce correlation or causation identity
rather than reuse `SensorId` for that purpose.

# 5. Runtime Model

The application maintains one latest `Measurement` per stable `SensorId` in an
in-memory `RuntimeStateStore`. Measurements contain only the sensor identity,
observed temperature and timezone-aware observation timestamp.

Timestamp admission runs before storage using the injected application
`Clock` and mandatory runtime-wide `max_future_skew`. This tolerance is a
non-negative `timedelta` with no default; zero is allowed. The future boundary
is inclusive. A measurement beyond `now + max_future_skew` remains observable
but is not stored, its timestamp is never rewritten, and existing runtime
state remains unchanged.

Runtime measurement state is used to prepare `ControlContext`. It is separate
from control state, which describes regulation or actuator condition.

Effective-temperature selection returns an immutable `ZoneTemperatureResult`
with one stable status: `effective`, `missing`, `expired` or `future_dated`.
Only `effective` references the exact stored measurement. The handler then
returns an immutable `TemperatureHandlingResult` containing exactly one typed
no-decision reason or the exact `DecisionCreatedEvent`.

For regulation, the application selects the exact latest measurement of the
zone's primary sensor. Secondary measurements remain stored and observable but
do not initiate regulation. Missing primary state produces no decision, and
there is no automatic fallback or synthetic zone measurement.

The application injects a deterministic `Clock` into aggregation; `SystemClock`
is the UTC infrastructure implementation. A primary measurement is eligible
when `now - primary_measurement_max_age <= timestamp <= now`. The cutoff is
inclusive, while future timestamps are strictly ineligible. A naive clock
value violates the port contract.

Admitted measurements continue through per-sensor ordering, which remains
distinct from elapsed-time freshness. Admitted old observations may be stored
and later rejected as expired. Admitted within-tolerance future observations
may be stored and observable while remaining temporarily ineligible for
regulation. There is no deletion or cleanup. Missing primary state returns no
effective measurement, while invalid primary configuration raises an explicit
error.

Freshness is evaluated only when aggregation is invoked. There is no timer,
silent-sensor reaction, fail-safe command, fallback or health monitoring, and
previously applied state remains unchanged when an observation is ineligible.
A positive skew tolerance deliberately creates a bounded window in which an
admitted future measurement can block later lower-timestamp inputs under the
unchanged store ordering rule. Zero tolerance provides the strongest poisoning
protection but may reject legitimate source-clock differences.

Admission rejection, same-sensor ordering rejection, freshness rejection,
missing primary state and configuration failure remain separate outcomes.
There is no rejection event, fallback, health monitoring or fail-safe command,
and observers cannot currently identify the exact no-decision reason from
`TemperatureMeasuredEvent` fields alone.

For every normally completed call, `ControlRuntime` returns an immutable
`RuntimeProcessingResult`. `RuntimeProcessingStatus` has stable codes for
`no_decision`, `decision_without_command`, `command_executed` and
`command_suppressed`. `TemperatureNoDecisionReason` provides stable codes for
admission rejection, out-of-order input, secondary input, missing primary
state, expired primary state and future-dated primary state.

Results reference existing `DecisionCreatedEvent` and `Command` objects rather
than duplicating decision, command, measurement or identifier fields. Expected
no-action outcomes are typed results. Configuration, clock, observer, actuator,
validation and unexpected failures remain exceptions and return no result.
Events remain notification-only, so event-only observers do not receive the
synchronous result. No logging, persistence, correlation identifiers or
diagnostic events are part of the model.

Arithmetic mean, weighted aggregation, cross-sensor timestamp comparison and
configurable aggregation policies remain outside the model. Repeated eligible
primary measurements may still produce repeated decisions.

Applied `ControlState` is stored separately per `ZoneId`. It contains only the
latest successfully executed logical action, the successful command identity
and the application time. It does not contain measurements, targets or desired
decisions.

An identical already-applied action is suppressed per zone. State changes only
after the actuator port returns normally; a failure leaves prior state intact
and permits a later request to retry. Decisions and decision events remain
observable even when execution is suppressed.

Applied state is in-memory and is lost on restart. A normal adapter return does
not physically confirm hardware state, and external changes can make the view
inaccurate. Persistence, state history, retries, physical feedback, routing and
concurrency protection are not implemented.

# 6. Historical Data Model

Historical measurements are not part of the runtime store. A future history
model may append observations and persist them, but the current runtime model
only retains the latest accepted measurement for each sensor.
