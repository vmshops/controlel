# Controlel

Controlel is a heating control integration for Home Assistant: it watches a room temperature sensor, decides when your zone needs heat, and — after safety checks — sends on/off commands to a heat source switch.

## What Controlel does

Controlel solves a common problem: a boiler or heat source that is switched on and off by a simple thermostat, with no explanation of *why* it acted and no protection against rapid cycling.

Controlel sits between your temperature sensor and your heat source and:

- **Decides when heat is needed** — based on your target temperature, a hysteresis deadband, and a confirmation interval that filters brief sensor drops.
- **Protects the heat source** — minimum on/off times (anti-cycling) mean a blocked transition is shown as *deferred* and reevaluated at its deadline, instead of replaying a stored command.
- **Explains its decisions** — every public entity, reason code, and decision trace is indexed in the [Home Assistant entity reference](docs/operations/EntityReference.md). You can see the latest decision, its reason, the requested command, and the service-call outcome.
- **Behaves safely by default** — new entries default to "Turn heating off" after a sensor timeout, and safety-disable commands bypass minimum-on protection.

Controlel is event-driven: it reacts to sensor state changes and deterministic deadlines. It does not poll.

## What Controlel does NOT do

It is important to know the boundary between a *command* and *physical reality*:

- **A successful command is not physical confirmation.** "Service call dispatched" means Home Assistant accepted the service call. Controlel never claims the valve is at a position, the burner is running, or the boiler is physically on. Unknown is not false.
- **One config entry, one zone, one primary sensor, one shared heat source.** There is no discovery, no multi-zone configuration UI, and no writable operational entities.
- **No persistence.** Measurements, demand, timers, and lockout state are in-memory only and are not restored across reload or restart.
- **No automatic retries** of failed service calls; failures are reported through logs and Repairs.
- **No water-temperature or efficiency optimization.** Physical water-target dispatch is intentionally unsupported.
- **Notifications are disabled by default** with no recipients; nothing is discovered or targeted automatically.
- **No persistent decision history.** Diagnostics expose only the bounded in-memory trace.
- **Custom-repository distribution only.** Controlel is not listed in the default HACS store.

The full list of current limitations is in the [Home Assistant installation guide](docs/operations/HomeAssistantInstallation.md).

## How it works (simple mental model)

```text
temperature sensor
      → zone demand (hysteresis + confirmation interval)
      → building demand
      → heat source permission (anti-cycling, minimum on/off)
      → safety checks (sensor validity, grace period, timeout action)
      → command (switch on/off)
```

- **Zone demand** — the sensor is compared against your target with a hysteresis deadband; a new heat demand must stay continuous for the confirmation interval.
- **Heat source permission** — the shared source policy checks minimum on/off protection. If a transition is blocked, it is deferred and reevaluated at its deadline.
- **Safety checks** — invalid, stale, or missing measurements do not become measurements; after the grace period the configured timeout action applies.
- **Command** — the result is a Home Assistant service call. Its success is command evidence, not physical feedback.

## Requirements

Before installing, make sure you have:

- Home Assistant `2026.7.3` or newer.
- Network access from Home Assistant to GitHub and PyPI.
- A temperature sensor with a finite numeric state and a Celsius or Fahrenheit unit.
- A dedicated Home Assistant entity (for example a switch) that can safely enable and disable the heat source.
- HACS, for the primary installation path.

Back up the Home Assistant configuration before installing or upgrading a custom integration.

## Installation

The supported distribution uses the public repository
`https://github.com/vmshops/controlel` as a HACS custom repository.

1. In HACS, open the menu and select **Custom repositories**.
2. Add `https://github.com/vmshops/controlel` with category **Integration**.
3. Download the latest released integration and restart Home Assistant.
4. Open **Settings > Devices & services > Add integration** and select
   **Controlel**.

The integration manifest makes Home Assistant install the exact public core
dependency `controlel==0.10.0`; users must not install the core manually.

A manual installation fallback (release ZIP with SHA-256 verification),
upgrade/rollback, and removal instructions are in the
[Home Assistant installation guide](docs/operations/HomeAssistantInstallation.md).

## First configuration

The setup form asks for only the zone and sensor names, a temperature sensor,
the target temperature, and one controlled switch. The temperature selector is
restricted to `sensor` entities with a temperature device class.

New entries default to a 21.0 °C target, a 15-minute maximum measurement age,
a 30-second future timestamp tolerance, a 2-minute sensor-failure grace period,
and **Turn heating off — recommended** after timeout.

In simple mode Controlel derives the enable/disable calls from the selected
switch (`switch.turn_on` / `switch.turn_off`) without asking for service names.
For equipment that is not one normal switch, select **Use custom Home
Assistant services** in the advanced settings.

What to expect on first setup:

- Setup subscribes to the configured temperature entity, processes its current
  state, and then starts the control runtime. A valid fresh measurement can
  therefore produce a heat-source service call immediately.
- An unknown, stale, or malformed state does not become a measurement; demand
  remains indeterminate during the grace period, after which the configured
  timeout action applies.
- A successful service return is not confirmation of physical heat-source
  state. Service failures are reported through logs and Repairs and are not
  retried automatically.

Existing entries can be edited through **Settings > Devices & services >
Controlel > Configure**; saving options preserves stable IDs and reloads the
entry.

## Support / reporting issues

- **Troubleshooting:** see the [Troubleshooting guide](docs/operations/Troubleshooting.md) for failure diagnosis.
- **Reporting defects:** open an issue at <https://github.com/vmshops/controlel/issues>. Include the integration version, Home Assistant version, relevant sanitized logs, and whether installation used HACS or the manual release archive.
- **Security reports:** see [SECURITY.md](SECURITY.md). Do not place credentials, private configuration, or exploit details in a public issue.
- **Diagnostics:** Home Assistant's config-entry diagnostics download contains normalized configuration, version data, the current operational snapshot, and a bounded in-memory trace.

## Developer section

> The following content is for contributors and maintainers. End users can
> stop reading here.

### Status

Project phase: Core M31C.1 heating-performance assessment foundation

Core package version: 0.11.0 (published on PyPI)
Home Assistant integration version: 0.11.0

Important: Home Assistant integration 0.11.0 intentionally depends on the
published Core 0.10.0 (see custom_components/controlel/manifest.json which pins
`controlel==0.10.0`). The repository also maintains the Core 0.11.0 candidate
(tag: `core-v0.11.0`) and its provenance records under `release-metadata/`.

M31C.1 is a passive observation and deterministic assessment foundation:
- passive assessment only (no control feedback)
- no polling
- no persistence
- explicit insufficient-evidence handling

Future milestones:
- M31C.2: planned anomaly transition / OperationalEvent policy work
- M31C.3: planned UserActivity → notification projection

Refer to `release-metadata/releases.yaml` and `docs/releases/` for canonical
release facts and human-oriented release pages.

### Home Assistant development integration

The reusable core remains under `src/controlel`. The first Home Assistant host
is a custom component under `custom_components/controlel`; its dependency
direction is strictly custom component to core.

The integration supports one config entry, one zone, one explicitly bound
temperature sensor, and one shared heat source. New entries use a filtered
temperature selector, generated stable IDs, safe timing defaults, and a simple
controlled-switch mode. Existing entries can be edited through **Configure**;
advanced mode preserves separate enable and disable service calls. Options
updates fully unload and rebuild the runtime. It uses a dedicated single-worker
executor for every synchronous `ControlRuntime` operation. No core method runs
on Home Assistant's event-loop thread.

The core runtime now supports deterministic multi-zone demand composition ahead
of a future Home Assistant multi-zone configuration UI. Hysteresis and demand
confirmation remain zone-local; a simple unweighted any-zone rule produces one
building demand for the unchanged shared-source protection and dispatch path.
Source minimum-time configuration is therefore not duplicated per zone.

Milestone 30 adds an optional zone heat-delivery branch after confirmed zone
demand. Existing entries remain unmanaged by default. The first Home Assistant
slice can drive a generic climate entity with deterministic setpoint assist:
confirmed heat selects a configured assist target and no heat restores the zone
target. Core contracts also model native, direct-position, binary, remote-
temperature, and multiple-actuator capabilities without vendor-specific logic.
Commanded and reported actuator state remain distinct; no command claims a
physical valve position without device feedback. Adaptive assist, learning,
actuator travel verification, and source-water-temperature control are not part
of this milestone.

New entries default to asymmetric hysteresis of 0.3 °C below and 0.1 °C above
the target, a two-minute heat-demand confirmation interval, plus command-based
minimum on/off times of 10/5 minutes. Existing entries resolve all five
settings to zero until the user explicitly changes them. The controller
preserves its last logical demand within the deadband and
reevaluates current demand at a lockout deadline instead of replaying a stored
command. Safety-disable commands bypass minimum-on protection; safety-enable
commands remain subject to minimum-off protection.

Source observability distinguishes a passive protection boundary from an
active lockout. `earliest_next_enable_time` and
`earliest_next_disable_time` may exist when no command is blocked. Active
lockout and deferred-command fields exist only while the current aggregate
demand requests a transition that protection prevents. A deadline callback
reevaluates current demand and protection instead of replaying a stored
command. Successful enable/disable dispatch timestamps are command evidence,
not physical boiler feedback; Controlel does not infer whether a burner or
boiler is physically running.

Milestone 30.2 adds core-only operational resilience contracts. Source
ownership distinguishes externally controlled sources from sources Controlel
may reconcile. Requested commands, successful or failed command outcomes,
reported controller state, and physical burner state remain separate evidence;
unknown is never treated as false. A Controlel-owned source with external-on,
no-heat drift and unknown transition age is held conservatively for five
minutes before corrective disable is considered. Failed or still-unconfirmed
correction remains retryable on a bounded 30-second cadence without polling or
command storms. Restart and reload begin with unknown transition history and
never reconstruct prior transitions.

The same core boundary adds explicit `NORMAL`, `SAFE_HEATING`,
`EMERGENCY_OFF`, and `MANUAL_RECOVERY_HEAT` operating modes. Recovery waits at
most 30 seconds for current demand and reported-source evidence. Manual
recovery defaults to two hours and is explicitly cancelled across reload.
Safe heating can produce a capability-gated `WATER_TARGET` intent, but physical
water-target dispatch is intentionally unsupported. Bounded diagnostics use
stable reason codes and never reinterpret permission or dispatch as physical
heat production.

Core 0.6.0 also includes M30.2D Runtime Supervision & Failsafe Recovery. An
application-level supervisor quarantines a failed normal-runtime generation,
transfers exclusive command authority to a minimal failsafe controller, and
uses protected `SAFE_HEATING` or `EMERGENCY_OFF` decisions while attempting a
bounded restart campaign. The Home Assistant host binds this supervisor
to its one-shot scheduler, failsafe and normal-runtime factories, and explicit
reported-source evidence. Supervision works only while the Home Assistant
process remains alive; it cannot protect against complete HA, OS, power, or
hardware failure.

Each entry creates one `Controlel — <Zone name>` device with a translated
operational summary and stable operational/diagnostic entities. The summary
describes logical demand, safety, deferred commands, requested commands, and
command outcomes; it never claims physical heat-source state. Configured
durations remain visible, while deadline and remaining entities are unavailable
when their countdown is inactive. Every public entity, value domain, source
projection, control relevance, and truthfulness warning is indexed in the
[Home Assistant entity reference](docs/operations/EntityReference.md).

The Options Flow offers Basic, Detailed, and Debug diagnostic profiles. New
0.5.0 and later entries default to Basic. Existing entries without a stored profile
resolve to Detailed, preserving periodic operational timing visibility without
a setup-time migration write. Basic refreshes presentation on meaningful
runtime events and retains 20 trace records; Detailed refreshes active
countdowns every 10 seconds and retains 100; Debug refreshes only active
countdown entities every second and retains 500. Debug expires after
60 minutes by default and returns to the previous Basic/Detailed profile, or can
be kept active until manually changed. Profiles affect presentation, logging,
and in-memory evidence only—not regulation.

Core 0.7.0 contains the M31A Operational Events Foundation: immutable
operational-event contracts; canonical category and severity taxonomies; and a
bounded in-memory stream with a default capacity of 200, deterministic ordering,
and explicit drop metadata. Transition and lifecycle de-duplication keeps the
stream semantic. Deterministic supervision-campaign correlation connects fatal,
failsafe, restart, and recovery evidence, while both normal and failsafe command
attempts and outcomes remain visible. Recorder failures are isolated from
control behavior, and `ControlRuntime.record_runtime_started()` is the narrow
public lifecycle boundary. Operational events remain separate from the decision
trace. M31A adds no notifications, statistics, persistence, polling, or control
behavior, and command dispatch or reported source state never claims physical
heat. Integration 0.9.0 exposes only the bounded, JSON-safe read projection in
downloaded diagnostics; it adds no Home Assistant event, entity, or control
surface.

Core 0.8.0 contains the M31B passive smart-notification foundation built on
that canonical stream. Core policy maps every event code to a distinct user
attention level, produces semantic localization-neutral intents, filters stable
logical recipients, applies explicit once-per-lifecycle versus per-occurrence
deduplication, and preserves safe scalar event details. An application service
owns the source cursor and reports exact missed-event gaps when the bounded
source stream overflows. Ordinary traffic is limited to 10 notifications per
recipient/category per 60 seconds; CRITICAL traffic has an independent 20 per
recipient per 60 seconds emergency ceiling. Delivery remains behind a generic
application port and is best-effort and in-memory, with no retry loop, polling,
persistence, or control-path influence. Bounded immutable notification state
and history retain truthful cursor and delivery evidence. Core `0.8.0` is
published and immutable.

Integration `0.10.1` composed Core `0.8.0` through a thin Home Assistant notify
transport. The `0.11.0` candidate migrates that transport to public Core
`0.10.0` and hosts the canonical `OperationalEventStream ->
UserActivityComposer -> UserActivityStream -> NotificationProcessor` path.
Notifications remain disabled with no recipients by default.
Configured delivery runs on the HA event loop through one coalesced drain task;
one recipient failure does not block another, unload rejects future drains, and
accepted HA service calls cannot be revoked. HA stores only validated modular
configuration and publishes bounded target-redacted diagnostics. Mapping,
deduplication, cursor/overflow accounting, and rate limits remain core-owned.
No polling, retry loop, persistence, automatic target discovery, custom sidebar
UI, or control-path influence is introduced.

Core `0.9.0` introduced the M31B.1 UserActivity Foundation as a separate
application/domain boundary. `OperationalEvent` remains fine-grained technical
evidence; immutable `UserActivity` records one human-meaningful occurrence;
notifications consume this activity boundary in M31B.2; and the decision trace remains
internal decision/debug evidence. Deterministic lifecycle IDs correlate source
reconciliation, measurement/safety incidents, building heating episodes, and
supervision without timestamp-proximity grouping. A passive
`UserActivityComposer` owns an exact source cursor, missed-event/overflow
accounting, bounded open lifecycle state, and a bounded in-memory activity
stream with explicit source-event provenance and truthful completion semantics.
Core `0.10.0` adds M31B.2 using the canonical one-way pipeline
`OperationalEventStream -> UserActivityComposer -> UserActivityStream ->
NotificationPlanner -> NotificationProcessor -> NotificationDeliveryPort`.
Activity level drives attention policy; intent provenance and de-duplication
bind to the activity and material lifecycle stage. There is no raw-event
production path, persistence, polling, retry loop, Home Assistant dependency,
or control influence. Integration `0.11.0` now hosts this pipeline without
reimplementing activity composition, policy, de-duplication, rate limits, or
cursor semantics.

The integration manifest requires the exact public core release
`controlel==0.10.0`. A supported custom-component deployment can therefore let
Home Assistant obtain the core dependency automatically; users do not need to
install the core manually. Editable installation remains available for local
source compatibility testing. The core test suite does not require Home
Assistant, while Home Assistant framework tests use separate local-source and
public-package compositions against the immutable public Core `0.10.0` release.

Framework compatibility is tested against Home Assistant `2026.7.3` with
`pytest-homeassistant-custom-component==0.13.347` on Python 3.14.2 or newer.
The isolated, hashed environment is defined by `requirements/ha-test.in` and
`requirements/ha-test.txt`; setup and suite commands are in the
[development guide](docs/development/DevelopmentGuide.md). The compatibility
harness is separate from HACS release validation. HACS metadata and
deterministic release packaging must pass before the unpublished `0.11.0`
candidate may be tagged; no default-store publication exists.

### Core package artifacts

The reusable core is published as the `controlel` distribution and import
package. Version `0.10.0` is the latest public immutable release. The static version source
and PEP 517 build configuration live in `pyproject.toml`; normal installation
depends only on Pydantic. Packaging validation builds one wheel and one sdist,
inspects their contents, and installs the wheel into a clean environment
outside the checkout.

Core versions `0.1.0`, `0.2.0`, `0.3.0`, `0.4.0`, `0.5.0`, `0.6.0`, `0.7.0`, `0.8.0`, `0.9.0`, and `0.10.0` are published on
PyPI and immutable. Future core corrections require a new version; rebuilt artifacts for an already
published version must never be uploaded.
Repository packaging CI remains validation-only and contains no publication
automation. See the [core release guide](docs/development/ReleaseGuide.md) for
the published release record, build validation, and version separation.

### Zone heat-demand confirmation

Core `0.3.0` inserts a zone-owned confirmation policy after hysteresis.
Milestone 29 keys that state independently per zone and places deterministic
building aggregation immediately afterward. Positive-duration heat demand must remain
continuous until its deadline; the deadline reevaluates current hysteresis
demand rather than replaying stored state. No-heat demand clears immediately.
Invalid, unavailable, stale, or future-dated input cancels a pending interval,
and valid recovery starts a complete new interval. Zero duration preserves
legacy immediate behavior.

This filter is separate from heat-source minimum-off protection and does not
detect an open window. The shared source policy consumes confirmed aggregate
demand only. Pending state is not persisted across reload or restart, and no
state claims that a physical heat source is on or off.

### Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Development guide](docs/development/DevelopmentGuide.md)
- [Release guide](docs/development/ReleaseGuide.md)
- [Home Assistant installation guide](docs/operations/HomeAssistantInstallation.md)
- [Home Assistant entity reference](docs/operations/EntityReference.md)
- [Troubleshooting](docs/operations/Troubleshooting.md)
- [Roadmap](docs/architecture/07_Roadmap.md)
