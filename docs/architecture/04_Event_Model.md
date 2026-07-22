# Event Model

## Decision notifications

Regulation produces a `Decision`, which describes what the regulation logic
decided and why. `ControlLoopService` wraps that result in a
`DecisionCreatedEvent`.

`ControlRuntime` publishes the event through `EventBus` so notification
subscribers can observe decisions. Command orchestration does not depend on a
subscriber return value: after publication, the runtime explicitly passes the
event to `DecisionEventHandler`.

The handler maps supported decision actions to an executable `Command`. A
decision may produce no command. Unsupported or non-actionable actions return
`None` and do not reach the actuator boundary.

A `Command` is an explicit request, not an event describing something that
already happened. No command-created event is introduced in the current flow.
