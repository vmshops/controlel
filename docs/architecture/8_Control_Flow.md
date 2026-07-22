# Control Flow

The synchronous in-memory runtime flow is:

```text
Measurement
-> TemperatureMeasuredEvent
-> RuntimeStateStore
-> ControlContext
-> Regulation
-> Decision
-> DecisionCreatedEvent
-> DecisionEventHandler
-> Command | None
-> CommandDispatcher
-> ActuatorPort
```

`Decision` remains a description of the regulation result. The application
handler explicitly maps `enable_heating` and `disable_heating` to commands in
the `heating` command family. Other actions produce no command.

`EventBus` publishes `DecisionCreatedEvent` for notification. Runtime command
creation is invoked explicitly and therefore does not depend on event
subscriber order or return values.

`CommandDispatcher` invokes the injected `ActuatorPort` once with the exact
command. Execution exceptions propagate to the caller. Repeated accepted
measurements may produce repeated commands.

The current flow intentionally has no command routing, retry policy,
idempotency or applied-state suppression. It also has no hardware adapter;
platform-specific implementations remain outside the core runtime.
