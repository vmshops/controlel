# Control Flow

The synchronous in-memory runtime flow is:

```text
Measurement
-> TemperatureMeasuredEvent
-> RuntimeStateStore
-> SensorRepository
-> Sensor.zone_id
-> ZoneRepository
-> Zone(zone_id, primary_sensor_id, target_temperature)
-> ZoneTemperatureAggregator
-> latest primary Measurement | None
-> ControlContext(sensor_id, zone_id)
-> Regulation
-> Decision(sensor_id, zone_id)
-> DecisionCreatedEvent
-> DecisionEventHandler
-> Command(zone_id) | None
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

The handler then validates the zone's configured primary sensor and retrieves
its exact latest measurement from runtime state. Only an accepted incoming
measurement from that primary sensor creates `ControlContext`. An accepted
secondary measurement remains stored and is subsequently published as a
temperature event, but produces no decision event or command—even when primary
state already exists. Missing primary state also produces no decision.

There is no fallback sensor, arithmetic or weighted aggregation, cross-sensor
timestamp comparison, or elapsed-time freshness rule. Configurable aggregation
policies remain outside the current flow.

Functional handlers are not subscribed by `ControlRuntime`. `EventBus` is
notification-only: it calls observers synchronously in registration order,
discards their return values and returns `None`. Observer return values cannot
change the functional result.

`Decision` remains a description of the regulation result. The application
handler explicitly maps `enable_heating` and `disable_heating` to commands in
the `heating` command family. Other actions produce no command.

`SensorId` is carried from the measurement through `ControlContext` into the
decision as observation provenance. The configured `ZoneId` is carried through
the same models as the logical regulated subject. `DecisionCreatedEvent`
contains the complete decision and does not duplicate either identifier.

Supported commands copy `Decision.zone_id` as their logical execution target.
They do not copy `SensorId`, reason, metadata or timestamp because those values
are not currently required for execution. Future durable causal tracing should
use explicit correlation or causation identity rather than overload
`SensorId`.

`EventBus` publishes `DecisionCreatedEvent` for notification before runtime
explicitly invokes command mapping. Decision publication is not a
request/response operation.

`CommandDispatcher` invokes the injected `ActuatorPort` once with the exact
command. Execution exceptions propagate to the caller. Repeated accepted
primary measurements may produce repeated commands; command-state suppression
is not part of this flow.

The current flow intentionally has no command routing, retry policy,
idempotency or applied-state suppression. It also has no hardware adapter;
platform-specific implementations remain outside the core runtime.

`ZoneId` is not a physical actuator identifier. Commands targeted to different
zones still pass through the same injected `ActuatorPort`; zone-to-actuator
routing is intentionally absent. Multiple sensors associated with one zone may
currently produce repeated or conflicting commands.

Observers may delay runtime processing, and observer exceptions currently
propagate to the caller. Observer isolation and concurrency are outside the
current design.

Scheduling, disabled-state behavior, configuration persistence and mutation,
and zone-based actuator routing are also outside the current flow.
