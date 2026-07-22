# Control Flow

The synchronous in-memory runtime flow is:

```text
Measurement
-> TemperatureMeasuredEvent
-> RuntimeStateStore
-> SensorRepository
-> Sensor.zone_id
-> ZoneRepository
-> Zone.target_temperature
-> ControlContext
-> Regulation
-> Decision
-> DecisionCreatedEvent
-> DecisionEventHandler
-> Command | None
-> CommandDispatcher
-> ActuatorPort
```

`ControlRuntime` explicitly invokes each functional handler. It processes a
temperature event through `TemperatureEventHandler` before publishing that
event to observers. A stale measurement produces no decision or command, but
its temperature event is still published.

For an accepted measurement, `TemperatureEventHandler` resolves the target
from explicit zone configuration using the measurement's typed `SensorId`.
Missing sensor or zone configuration raises without a fallback. The accepted
measurement remains recorded, functional processing stops before a decision,
and the temperature event is not published because functional handling occurs
before observer notification.

Functional handlers are not subscribed by `ControlRuntime`. `EventBus` is
notification-only: it calls observers synchronously in registration order,
discards their return values and returns `None`. Observer return values cannot
change the functional result.

`Decision` remains a description of the regulation result. The application
handler explicitly maps `enable_heating` and `disable_heating` to commands in
the `heating` command family. Other actions produce no command.

`EventBus` publishes `DecisionCreatedEvent` for notification before runtime
explicitly invokes command mapping. Decision publication is not a
request/response operation.

`CommandDispatcher` invokes the injected `ActuatorPort` once with the exact
command. Execution exceptions propagate to the caller. Repeated accepted
measurements may produce repeated commands.

The current flow intentionally has no command routing, retry policy,
idempotency or applied-state suppression. It also has no hardware adapter;
platform-specific implementations remain outside the core runtime.

Observers may delay runtime processing, and observer exceptions currently
propagate to the caller. Observer isolation and concurrency are outside the
current design.

Scheduling, disabled-state behavior, configuration persistence and mutation,
zone-based actuator routing, and decision/command zone identity are also
outside the current flow.
