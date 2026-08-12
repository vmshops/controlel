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

## Core 0.6.0 source-resilience diagnostics

The core 0.6.0 candidate adds immutable
`SourceResilienceDiagnosticsV1`. Its fixed bounded projection contains schema
version 1, evidence-derived update time, operating mode and reason, desired and
reported source state, observation time, last successful command, ownership,
capabilities, drift/reconciliation state, transition-history knowledge,
recovery state, corrective intent or blocking boundary, manual-recovery timing,
safe-heating degradation, and optional water-target intent.

Values use stable reason codes and JSON-safe scalars or bounded tuples. Unknown
evidence remains null or an explicit unknown code; it is never rendered as
false. No raw sample history, arbitrary exception message, secret, or physical
burner/heat confirmation is included. Successful command dispatch and reported
controller state remain separate fields.

This application-level contract is part of the core release only. Home
Assistant integration `0.8.0` remains pinned to core `0.5.0` and does not adopt
or publish the new source-resilience projection in this release boundary.

M30.2D adds immutable `RuntimeSupervisionDiagnosticsV1` for supervisor state,
active command authority, normal generation, normalized fatal cause code,
failsafe mode/reason, restart attempts and budget, next eligibility, exhaustion,
manual-recovery deadline, and last successful normal recovery. The projection
is fixed-size and contains no traceback or arbitrary error message.
