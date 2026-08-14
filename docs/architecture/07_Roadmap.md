# Roadmap

Milestone 26 uses published immutable core `0.2.0` and released integration
`0.4.0` with
asymmetric hysteresis, command-dispatch-based minimum on/off protection,
deferred deadline reevaluation, and operational diagnostics. Persistence of
hysteresis/source-control history is explicitly deferred; restart begins with
unknown dispatch history and no fabricated lockout.

Milestone 26.1 prepares integration `0.5.0` with Basic, Detailed, and Debug
diagnostic profiles; stable timing entities; a translated operational summary;
allowlisted observability diagnostics; and one lifecycle-owned active-countdown
refresh scheduler. It does not change core decisions or claim physical
heat-source feedback.

Milestone 27 prepares core `0.3.0` and integration `0.6.0`. It adds a
zone-owned, continuously valid heat-demand confirmation interval between
hysteresis and demand arbitration. Existing entries default to immediate
zero-duration behavior; new entries default to two minutes. Pending state is
not persisted, and this filter is explicitly distinct from both shared-source
minimum-off protection and future open-window detection. Phase A kept the
manifest pinned to `controlel==0.2.0`; after the separately approved public
core `0.3.0` release, Phase C pins the integration to `controlel==0.3.0` and
validates both local-source and public-package compositions.

Milestone 28 uses published immutable core `0.4.0` and prepares integration
`0.7.0`. It replaces ambiguous source timing observations with one
immutable state model that separates passive enable/disable boundaries, active
minimum-time lockout, deferred commands, successful dispatch evidence, and
safety bypass. Regulation, command timing, anti-cycling, confirmation, and
fatal behavior remain equivalent to core 0.3.0/integration 0.6.0. Phase C sets
the integration manifest to `0.7.0`, pins `controlel==0.4.0`, and validates
both local-source and public-PyPI framework compositions.

Milestone 28 is complete. Milestone 29 prepared core `0.5.0` with multi-zone heat-demand
aggregation: zone-local hysteresis and confirmation feed a deterministic,
unweighted any-zone building demand while the existing shared-source control
and safety policies remain global. During that core Phase A work, the Home
Assistant `0.7.0` candidate continued exposing its one-zone configuration
contract. No priorities, weights, or source duplication are included.

Milestone 29 is complete, and its core boundary is published as immutable
`controlel==0.5.0`. Milestone 30 introduces capability-based,
vendor-independent zone heat-delivery actuators separately from building demand
and shared-source protection. The core supports native control, deterministic
setpoint assist, configured direct position, binary valves, optional valid-only
remote-temperature forwarding, truthful command evidence, and stable
multiple-actuator identity/order. The first Home Assistant slice exposes one
generic climate setpoint-assist actuator per entry. It does not retroactively
make actuators part of the Milestone 29 aggregation rule.

Milestone 30.1A adds bounded, in-memory heating-episode observation without a
new control loop. Milestone 30.1B adds deterministic shadow-only performance
assessment. Milestone 30.1C projects that evidence through an immutable,
bounded application diagnostic contract for read-only Home Assistant
presentation. These stages create no actuator or source commands and do not
feed control decisions.

Integration `0.8.0` is the M30.1C Home Assistant release candidate. It retains
the one-zone configuration surface, consumes immutable `controlel==0.5.0`, and
adds only read-only diagnostic presentation.

Milestone 30.2 is merged and prepares core `0.6.0` with operational resilience
and recovery. It adds explicit source ownership and capabilities, truthful
reported-source evidence, bounded external-drift reconciliation, bounded
restart recovery, four explicit operating modes, and immutable reason-coded
source-resilience diagnostics. Unknown transition age receives a conservative
five-minute hold; recovery and corrective retry boundaries are 30 seconds; and
manual recovery defaults to two hours with explicit reload cancellation.
Source safety remains authoritative. A capability-gated `WATER_TARGET` value is
intent only, and physical water-target dispatch remains unsupported.

Core `0.6.0` is published and immutable. Integration `0.8.2` consumes it in a
focused stabilization boundary that binds reported-source evidence and core
runtime supervision into the existing Home Assistant host. It also fixes
worker-thread diagnostic refresh publication without adding polling or new
operating-mode controls.

M30.2D stops the earlier 0.6.0 release candidate after a real scheduled
timestamp-coherence fatal. It refreshes unchanged confirmation evidence on
every aggregate evaluation and adds explicit normal/failsafe command authority,
generation quarantine, bounded fixed-interval restart campaigns, minimal safe
heating/emergency-off control, and bounded reason-code supervision diagnostics.
The earlier `d7bfe426db90a21fed9cb9cae6591c310c0c9d42` pre-tag artifacts are obsolete
and must never be published.

Adaptive assistance remains future work. Learning, persistence, actuator
travel/open verification, and source-water-temperature optimization also
remain future layers.

## Milestone 31A: operational events foundation

M31A is published as immutable core `0.7.0`. Home Assistant integration `0.9.0`
pins that exact public package and exposes the read-only JSON projection through
downloaded diagnostics only.

M31A adds a canonical immutable operational-event schema, stable category and
severity taxonomies, transition-aware application recording, and a
thread-safe bounded 200-event in-memory stream with explicit drop metadata.
Ordering and drop accounting are deterministic. Transition/lifecycle
de-duplication and deterministic supervision campaign correlation cover normal
and failsafe command evidence without correlating unsupported reported state.
Recorder failures remain isolated, and the narrow public runtime lifecycle
boundary avoids exposing private runtime helpers. The read boundary is
immutable and JSON-safe, the decision trace remains separate, and no polling,
persistence, notification delivery, statistics, or control influence is
introduced. Existing entity keys and unique IDs remain unchanged.

M31B is published as immutable core `0.8.0` and remains a passive
consumer of this boundary. It defines immutable recipient, policy, intent,
delivery-result, and bounded read-state contracts; exhaustive
event-to-attention-level mapping; explicit once-per-lifecycle and
per-occurrence de-duplication; an application-owned source cursor with exact
missed-event/overflow accounting; ordinary per-recipient/category rate
limiting; an independent CRITICAL emergency ceiling; and a generic delivery
port. Bounded immutable state/history records normalized outcomes and truthful
cursor/overflow evidence. Integration `0.10.0` adds only validated HA
configuration, a notify-service delivery adapter, one coalesced event-loop
drain, unload handling, and bounded redacted diagnostics. Core still owns event
mapping, deduplication, cursors, overflow accounting, and rate limits. Neither
layer adds polling, retries, persistence, automatic targets, or control
influence. The custom sidebar UI and its write/test APIs remain deferred. M31C
may add explainable statistics/analytics and must
preserve the command/report/physical-reality distinctions.

Integration `0.10.1` is the presentation-only follow-up: HA renders every
reachable notification code into localized human-readable text with safe
allowlisted interpolation and fail-safe generic fallback. Notification selection
and M31B transport semantics are unchanged.

M31B.1 is published as immutable Core `0.9.0`. It adds immutable bounded activity contracts,
deterministic activity IDs, explicit reconciliation/measurement/building-heating
lifecycle evidence, source-event provenance, and a passive composer with
truthful cursor, missed-event, overflow, and bounded-open-state accounting.
`OperationalEvent` remains technical evidence, `UserActivity` is a
human-meaningful occurrence, Notification was reserved as its future consumer, and
Decision Trace remains internal decision/debug evidence. There is no
time-proximity grouping, HA dependency, persistence, polling, analytics,
notification remapping, or control influence.
M31B.2 is the unpublished Core `0.10.0` release candidate and makes
`UserActivity` the canonical Core notification input. It adds
exhaustive activity-type/lifecycle policy, activity-level attention filtering,
activity-bound intent provenance and de-duplication, and exact bounded activity
revision cursor/overflow accounting while preserving bounded history, ordinary
rate limits, the independent CRITICAL ceiling, and the generic delivery port.
There is no raw `OperationalEvent` notification production path, HA dependency,
polling, retry loop, persistence, or control influence. A separate HA `0.11.0`
change may later consume the published Core `0.10.0` boundary and is not part of
M31B.2.

## Milestone 23: Home Assistant one-zone host vertical slice

The first host integration proves:

```text
configured HA temperature entity
-> Measurement
-> dedicated serialized ControlRuntime worker
-> HeatSourceCommand
-> configured blocking HA service call
```

Scope is one config entry, one zone, one primary sensor, and one shared heat
source. It includes config flow, lifecycle, initial-state buffering, a
one-shot Home Assistant scheduler, typed runtime data, and Repairs issues for
operational failures.

Deferred work included multi-zone configuration UI, options/reconfigure flows,
persistence, discovery, polling, diagnostic entities, HACS packaging, physical
confirmation, generic service data, retries, hardware protocols, modulation,
DHW, valves, learning, and frontend panels.

Before normal HACS distribution, the reusable core must be released as a
versioned package and referenced by a pinned custom-component requirement.

## Milestone 24B: controlled core release

Milestone 24B1 prepared the `controlel` core distribution with explicit PEP 517
metadata, wheel and sdist content validation, clean out-of-checkout wheel
installation, and non-publishing packaging CI.

Milestone 24B2 published immutable core `controlel==0.1.0` and independently
verified its public files. Integration `0.1.1` pins that exact dependency and
CI validates both local editable compatibility and an isolated public package
composition. Core and integration versions now evolve independently.

At the conclusion of Milestone 24B, HACS metadata, brands metadata,
integration tagging, GitHub release packaging, and end-user HACS distribution
remained later release work.

## Milestone 24C: controlled Home Assistant distribution

Milestone 24C1 adds HACS metadata, a deterministic allowlisted integration ZIP,
independent archive validation, non-publishing CI, removal cleanup, and
end-user documentation. It does not create a tag or release.

Milestone 24C2 is the separately approved integration tag, GitHub Release, and
clean custom-HACS installation validation. The repository-wide release stream
is reserved for integration releases; core provenance may use tags but not
GitHub Releases in this monorepo.

Milestone 24C3 remains optional Home Assistant Brands work and submission to
the HACS default repository after the custom-repository release is stable.

## Milestone 25A: editable configuration UX

Milestone 25A prepares integration `0.2.0` while retaining core
`controlel==0.1.0`. It adds generated stable IDs, filtered temperature
selection, safe defaults, a simple controlled-switch mode, lossless advanced
service bindings, and a two-step Options Flow. Existing `0.1.1` entries load
without migration: mutable options override legacy data, while IDs remain
stable in entry data. Every successful update fully unloads and reconstructs
one runtime.

## Milestone 25B: operational visibility

Milestone 25B prepares integration `0.3.0` with one immutable integration-side
operational snapshot, one zone-controller device, read-only operational and
diagnostic entities, explicit measurement/demand/safety/command states, and
allowlisted config-entry diagnostics. A bounded 20-record decision trace and
all snapshot state are in memory only. Entity unique IDs use the config entry
ID, so display-name changes and reloads do not duplicate entities. This
milestone does not change core `0.1.0` heating behavior and does not claim
physical output confirmation.

Milestone 25B.1 prepares the focused `0.3.1` integration patch with
configuration provenance, exact seconds/minutes Options Flow round trips,
allowlisted configuration-change logging, clearer entity presentation, and
truthful grace countdown and deadline visibility. Core behavior remains
unchanged at `0.1.0`.

The Home Assistant configuration UI still defers multiple zones or sensors,
persistence, climate/number/select entities, physical output feedback,
automatic retry, heating curves, modulation, DHW, learning, and dashboard work.
Core Milestone 29 supplies the multi-zone demand architecture before that UI is
introduced. Versions `0.3.0` and `0.3.1` are the published integration line
preceding Milestone 26.
