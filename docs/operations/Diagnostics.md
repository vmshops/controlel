# Source-control diagnostics

Downloaded diagnostics expose a fixed operational snapshot. Milestone 28 adds
stable source fields for aggregate demand, source-control state, passive
earliest-next-enable/disable timestamps, active lockout type/deadline/remaining,
deferred command/reason/start/deadline/remaining, last successful enable and
disable dispatches, safety-bypass evidence, and last requested command/outcome.

Configuration is normalized before export. Raw config-entry data and options
are limited to explicit allowlists, unknown keys are omitted, and failures are
represented by stable type/outcome codes rather than arbitrary exception text.
No secrets or arbitrary service data are exported.

Passive protection timestamps are low-churn facts and do not install a refresh
timer. Basic diagnostics are event-driven. Detailed refreshes only active
countdowns every 10 seconds; Debug uses 1 second. Both active-lockout remaining
and deferred remaining derive from the same deadline and the existing
observability scheduler. Users may exclude high-frequency remaining-time
entities from Recorder; Controlel never changes Recorder automatically.

None of these fields is physical source feedback. A successful dispatch proves
only that the configured adapter call completed without error.
