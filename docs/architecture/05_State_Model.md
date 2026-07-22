# State Model

## Latest runtime measurement state

`RuntimeStateStore` is an application-layer, in-memory view of the latest
accepted sensor measurements. It stores at most one `Measurement` per
`SensorId` and exists only for the lifetime of the running process.

A measurement is an observed fact containing a stable sensor identifier, an
observed temperature and a timezone-aware observation timestamp. Newer
measurements replace older measurements. Equal timestamps are resolved by
arrival order, while an older measurement is rejected.

Before the store sees an incoming measurement, the application validates its
timestamp against one mandatory runtime-wide `max_future_skew`. The value is a
non-negative `timedelta` with no default; zero is allowed. The validator reads
the injected `Clock` once and admits timestamps at or before the inclusive
boundary:

```text
measurement.timestamp <= now + max_future_skew
```

A timestamp beyond that boundary is rejected without rewriting it or changing
existing runtime state. The rejected input remains observable as a
`TemperatureMeasuredEvent` but is not stored.

The store is updated from measurement events before a `ControlContext` is
prepared. This preserves the flow:

```text
Sensor -> Measurement -> Event -> RuntimeStateStore -> ControlContext
       -> Decision -> DecisionCreatedEvent -> Command | None -> ActuatorPort
```

The measurement's `SensorId` is observation provenance. Target resolution adds
the configured `ZoneId`, and both identifiers are preserved in
`ControlContext` and `Decision`. A produced command retains only `ZoneId` as
its logical execution target; these identifiers are not runtime state fields
added by the store.

## Effective zone temperature

Each zone configures one required `primary_sensor_id`. The application validates
that this sensor is registered and belongs to the zone, then reads its exact
latest `Measurement` from `RuntimeStateStore`. That observation is the sole
current-temperature input for zone regulation.

`ZoneTemperatureAggregator` returns an immutable `ZoneTemperatureResult`
instead of an ambiguous optional measurement. Its stable statuses are
`effective`, `missing`, `expired` and `future_dated`. Only `effective` contains
the exact stored `Measurement`; all other statuses contain no measurement.

Each zone also requires a strictly positive
`primary_measurement_max_age`. `ZoneTemperatureAggregator` reads the injected
application `Clock` exactly once and accepts the primary observation when:

```text
now - primary_measurement_max_age <= measurement.timestamp <= now
```

The cutoff is inclusive. A timestamp older than the cutoff is expired; a
timestamp later than `now` is future-dated and is strictly ineligible for
regulation. `Clock.now()` must be timezone-aware. Production composition can
provide the UTC `SystemClock` infrastructure adapter, while tests provide a
deterministic clock.

Secondary sensor measurements remain per-`SensorId` runtime observations but
do not initiate regulation. There is no automatic fallback when primary state
is missing, and invalid primary configuration raises an explicit application
error. The store contains no synthetic zone measurement and is not mutated by
effective-temperature selection.

Timestamp admission, out-of-order rejection and elapsed-time expiry are
distinct. Admission protects the store from excessive future timestamps.
Admitted measurements then enter the unchanged same-sensor ordering rule.
Admitted old measurements may be stored and are handled later by freshness,
which remains a per-zone eligibility rule evaluated only when aggregation
runs. No timestamps are compared across sensors.

Missing primary state returns no effective measurement. Expired observations
and admitted within-tolerance future observations also return no effective
measurement, but remain stored and observable; no deletion or cleanup occurs.
Invalid primary configuration continues to raise its explicit missing-sensor
or zone-mismatch exception.

`TemperatureEventHandler` maps these state outcomes into an immutable
`TemperatureHandlingResult`, which contains exactly one of a typed no-decision
reason or the exact `DecisionCreatedEvent`. The handler does not create or
dispatch commands.

There is no background timer, polling, fallback sensor or health monitor. A
sensor that silently stops reporting triggers no immediate action. Expiry does
not create a fail-safe command, and previously applied control state remains
unchanged.

A positive skew tolerance deliberately permits a bounded future timestamp to
become the latest per-sensor value and temporarily reject a later lower
timestamp under the unchanged ordering contract. Zero tolerance provides the
strongest poisoning protection but may reject legitimate clock differences.
No timestamp rewriting, cleanup, fallback, health monitoring or fail-safe
command exists.

## Historical measurements

Latest runtime state is not measurement history. The runtime store overwrites
the current value for a sensor and exposes no append or history query API.
Historical storage will be a separate future capability with its own retention
and persistence design.

## Control state

`ControlState` records the latest successfully applied logical action for one
`ZoneId`. `StateRepository` retains at most one immutable state per zone. A
state contains the applied action, the exact successful `Command.id` and a
timezone-aware application time. It contains no current measurement or target
configuration and is not stored in `RuntimeStateStore`.

Before actuator execution, the application checks the zone's applied state. An
identical action is suppressed without changing state. A different or missing
state permits execution, and the repository is updated only after
`ActuatorPort.execute()` returns normally. A failure propagates and leaves any
previous state unchanged, allowing a later measurement to request the action
again.

Applied state is in-memory and lost on restart, so the first command after a
restart may execute again. A normal adapter return is application-level
success, not physical hardware confirmation. External hardware changes can
therefore make the in-memory state inaccurate.

## Configuration and targets

Target temperatures and other regulation settings are configuration inputs.
For an accepted measurement, the application resolves its `SensorId` through
the Sensor Repository, follows `Sensor.zone_id`, and reads the typed target
from the Zone Repository. The target is added while preparing `ControlContext`.
It is not a field of `Measurement` and is not stored as latest sensor state.

Missing sensor or zone configuration raises an explicit application
configuration error. No fallback target is applied. Because the measurement is
recorded before configuration resolution, an accepted observation remains in
runtime state when resolution fails, but no regulation decision is produced.

All commands are still dispatched through one injected `ActuatorPort`.
`ZoneId` is not a physical actuator identifier, and zone-to-actuator routing is
not part of the current state or configuration model.

## Persistence boundary

`RuntimeStateStore` has no database, integration or plugin dependency. Process
restart recovery and durable storage are outside the current state model.
Applied control state is also non-persistent. There is no applied-state history,
retry mechanism, physical feedback, routing or concurrency protection.
