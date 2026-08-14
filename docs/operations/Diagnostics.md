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

Core 0.6.0 adds immutable
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

Home Assistant integration `0.10.1` consumes core `0.8.0` and includes the bounded
runtime-supervision projection to downloaded diagnostics. It reports phase,
command authority, normalized fatal cause, restart attempts/budget/deadline,
and recovery timestamps without arbitrary exception text or physical-state
claims.

M30.2D adds immutable `RuntimeSupervisionDiagnosticsV1` for supervisor state,
active command authority, normal generation, normalized fatal cause code,
failsafe mode/reason, restart attempts and budget, next eligibility, exhaustion,
manual-recovery deadline, and last successful normal recovery. The projection
is fixed-size and contains no traceback or arbitrary error message.

The authoritative per-entity quick reference, including diagnostics-only
M30.2/M30.2D fields, is [EntityReference.md](EntityReference.md).

## M31A bounded operational events

Downloaded diagnostics include an `operational_events` object with schema
version, capacity, total/retained/dropped counts, latest event timestamp, and
at most 200 ordered semantic events. Event fields are localization-neutral
codes and JSON-safe evidence. Unknown evidence remains null; arbitrary
exception messages, service payloads, secrets, and physical-state inferences
are excluded.

This stream is separate from `decision_trace`: it records meaningful
transitions rather than every evaluation. It is diagnostics-only, in memory,
and passive. Downloading or refreshing diagnostics emits no events and creates
no timer, polling, command, Home Assistant event, or Recorder history.

## M31B notification diagnostics

Downloaded diagnostics include a separate `notification_policy` object with
schema version 1, enabled state, redacted recipient summaries, bounded outcome
counters, latest intent and delivery evidence, and at most the configured
bounded number of recent semantic intent/result records. It also reports
`source_total_observed`, `source_last_processed_sequence`,
`source_events_missed`, and `source_overflow_occurrences`. Transport targets
are never returned; diagnostics show only whether a target is configured.
Arbitrary service exceptions, secrets, tokens, and localized prose are
excluded.

The subsystem is disabled with no recipients by default. History, cursor, and
rate-limit state are memory-only. If retention overtakes the notification
cursor, the exact sequence gap is counted rather than reconstructed. Delivery
runs outside serialized control through one coalesced HA drain task. A failed
notify service becomes a stable `failed` result and cannot alter commands,
source authority, runtime lifecycle, event retention, or later evaluations.
