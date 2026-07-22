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

Runtime measurement state is used to prepare `ControlContext`. It is separate
from control state, which describes regulation or actuator condition.

For regulation, the application selects the exact latest measurement of the
zone's primary sensor. Secondary measurements remain stored and observable but
do not initiate regulation. Missing primary state produces no decision, and
there is no automatic fallback or synthetic zone measurement.

The application injects a deterministic `Clock` into aggregation; `SystemClock`
is the UTC infrastructure implementation. A primary measurement is eligible
when `now - primary_measurement_max_age <= timestamp <= now`. The cutoff is
inclusive, while future timestamps are strictly ineligible. A naive clock
value violates the port contract.

Timestamp ordering remains per sensor and is distinct from elapsed-time
freshness. Expired and future observations remain stored and observable, and
there is no deletion or cleanup. Missing primary state returns no effective
measurement, while invalid primary configuration raises an explicit error.

Freshness is evaluated only when aggregation is invoked. There is no timer,
silent-sensor reaction, fail-safe command, fallback or health monitoring, and
previously applied state remains unchanged when an observation is ineligible.
A stored future-dated measurement can block later lower-timestamp inputs under
the unchanged store ordering rule. Clock-skew tolerance and timestamp admission
remain future work.

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
