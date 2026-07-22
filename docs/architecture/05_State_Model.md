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

## Historical measurements

Latest runtime state is not measurement history. The runtime store overwrites
the current value for a sensor and exposes no append or history query API.
Historical storage will be a separate future capability with its own retention
and persistence design.

## Control state

Control state describes the condition or output of the regulation process,
such as whether heating is enabled. It is distinct from sensor observations.
The existing domain `ControlState` and `StateRepository` are not used as the
latest measurement store.

## Configuration and targets

Target temperatures and other regulation settings are configuration inputs.
They are supplied explicitly when the runtime is composed and are added while
preparing `ControlContext`. They are not fields of `Measurement` and are not
stored as latest sensor state.

## Persistence boundary

`RuntimeStateStore` has no database, integration or plugin dependency. Process
restart recovery and durable storage are outside the current state model.
