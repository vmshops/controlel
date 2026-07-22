# Event Model

## Notification contract

`EventBus` is a synchronous observer-notification mechanism. It notifies every
matching subscriber in registration order, discards subscriber return values
and always returns `None`. Dictionary event keys and class-based event keys are
both supported.

Functional handlers are invoked explicitly by `ControlRuntime`; they are not
also subscribed by the runtime. This avoids duplicate execution and prevents
functional results from depending on subscriber ordering.

Temperature measurement processing occurs before `TemperatureMeasuredEvent`
is published. Observers therefore cannot alter the event before runtime state
and regulation have processed it. Rejected stale measurement events are still
published and remain observable.

Subscribers run synchronously and may delay runtime processing. Subscriber
exceptions currently propagate unchanged.

## Decision notifications

Regulation produces a `Decision`, which describes what the regulation logic
decided and why. `ControlLoopService` wraps that result in a
`DecisionCreatedEvent`.

`ControlRuntime` publishes the event through `EventBus` so notification
subscribers can observe decisions. Decision events are notifications, not
request/response calls. After publication, the runtime explicitly passes the
event to `DecisionEventHandler`.

The contained `Decision` is the authoritative source of its `SensorId`
observation provenance and `ZoneId` regulated-subject identity.
`DecisionCreatedEvent` does not duplicate those identifiers as event fields.

The handler maps supported decision actions to an executable `Command`. A
decision may produce no command. Unsupported or non-actionable actions return
`None` and do not reach the actuator boundary.

A `Command` is an explicit request, not an event describing something that
already happened. No command-created event is introduced in the current flow.
Commands carry the decision's `ZoneId` as a logical execution target but do not
carry `SensorId`.
