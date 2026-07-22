# State Model

## Latest runtime measurement state

`RuntimeStateStore` is an application-layer, in-memory view of the latest
accepted sensor measurements. It stores at most one `Measurement` per
`SensorId` and exists only for the lifetime of the running process.

A measurement is an observed fact containing a stable sensor identifier, an
observed temperature and a timezone-aware observation timestamp. Newer
measurements replace older measurements. Equal timestamps are resolved by
arrival order, while an older measurement is rejected.

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

Out-of-order rejection and elapsed-time expiry are distinct. Ordering remains
a same-sensor store rule; freshness is a per-zone eligibility rule evaluated
only when aggregation runs. No timestamps are compared across sensors.

Missing primary state returns no effective measurement. Expired and
future-dated observations also return no effective measurement, but remain
stored and observable; no deletion or cleanup occurs. Invalid primary
configuration continues to raise its explicit missing-sensor or zone-mismatch
exception.

There is no background timer, polling, fallback sensor or health monitor. A
sensor that silently stops reporting triggers no immediate action. Expiry does
not create a fail-safe command, and previously applied control state remains
unchanged.

A future-dated observation can remain the latest per-sensor value and cause a
later lower-timestamp observation to be rejected under the unchanged ordering
contract. Timestamp admission and clock-skew tolerance are future policy work.

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
