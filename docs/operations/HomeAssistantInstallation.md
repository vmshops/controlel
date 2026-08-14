# Home Assistant installation

## Hysteresis and anti-cycling settings

New entries use a 0.3 Â°C turn-on differential, 0.1 Â°C turn-off differential,
10-minute minimum on time, and 5-minute minimum off time. Existing entries keep
legacy exact-threshold/immediate-switching behavior through zero values until
changed in **Configure**. Minimum times start when a command is successfully
dispatched; they do not confirm the physical heat source changed state.

Inside the hysteresis deadband Controlel preserves its last accepted logical
demand. A blocked transition is shown as deferred and reevaluated at its
deadline. Safety timeout disable bypasses minimum-on protection, while safety
timeout enable does not bypass minimum-off protection.

Protection history is not persisted. After restart or reload, Controlel reads
the current sensor value deterministically but does not infer prior command
history or lockout state from the switch.

Controlel `0.10.0` is the current development candidate for one heating zone,
one primary temperature sensor, and one shared heat source. It requires the
public core package `controlel==0.8.0`.

Integration `0.10.0` uses published immutable core `0.8.0`. It retains the
thread-safe entity publication and runtime-supervision host binding needed for
M30.2 while retaining the existing configuration surface and entity identity.
The configured simple switch is explicitly Controlel-owned because this
integration actively commands it. Its `on`, `off`, `unknown`, and `unavailable`
states are forwarded as reported controller evidence for reconciliation. That
evidence is never presented as burner operation or reconstructed command
history.

### Heat-source timing observations

- **Earliest next enable/disable** is a passive timestamp calculated from the
  last successful opposite command. Its presence does not mean a command is
  blocked.
- **Active lockout** appears only when current aggregate demand requests a
  command before its passive boundary. Type, deadline, and remaining time then
  identify the protection that is actually blocking it.
- **Deferred command** exists only for that blocked request. Its reason, start,
  deadline, and remaining time clear if demand changes or after deadline
  reevaluation.
- **Confirmed zone demand** is the output of the zone confirmation filter. It
  remains independent of source minimum-off protection.
- **Successful dispatch** means the configured Home Assistant service call
  returned successfully. It is not physical boiler or burner feedback.

Basic is event-driven and does not refresh passive timestamps. Detailed and
Debug refresh active lockout/deferred remaining-time entities every 10 seconds
and 1 second respectively, using the existing observability scheduler.
High-frequency remaining-time entities may be excluded from Recorder if their
history is not useful. Passive timestamp entities are low-churn. Controlel does
not modify Recorder configuration automatically.

Candidate `0.10.0` is not published; use the latest published integration for
HACS custom-repository installation. Controlel is not listed in the default HACS
store.

After installation, use the
[Home Assistant entity reference](EntityReference.md) to interpret every
public entity and downloaded-diagnostics-only resilience field.

Milestone 27 adds **Heat-demand confirmation time** to the zone settings.
New entries default to 2 minutes. Entries created by 0.5.0 or older that lack
the stored field resolve to 0 seconds and retain immediate heat-demand
handoff. Fractional minutes are preserved as exact runtime seconds. The value
must be finite, non-negative, and no greater than 24 hours.

The interval filters brief drops below the hysteresis threshold. It is not the
heat source minimum-off time and does not detect open windows. An unavailable,
unknown, invalid, stale, or future-dated measurement resets a pending interval.
Reload and restart also begin a fresh interval; confirmation history is not
persisted.

## Prerequisites

- Home Assistant `2026.7.3` or newer.
- Network access from Home Assistant to GitHub and PyPI.
- A temperature sensor with a finite numeric state and a Celsius or Fahrenheit
  unit.
- A dedicated Home Assistant entity that can safely enable and disable the
  heat source.
- HACS, for the primary installation path.

Back up the Home Assistant configuration before installing or upgrading a
custom integration.

## HACS custom-repository installation

1. Open HACS.
2. Open the top-right menu and select **Custom repositories**.
3. Enter `https://github.com/vmshops/controlel`.
4. Select category **Integration** and add the repository.
5. Open Controlel and download the latest released version.
6. Restart Home Assistant when HACS requests it.
7. Open **Settings > Devices & services > Add integration**.
8. Search for **Controlel** and complete the config flow.

HACS downloads the release asset into
`config/custom_components/controlel/`. During integration setup, Home
Assistant reads the manifest and installs `controlel==0.8.0` from PyPI.
Manual core installation is neither required nor supported for normal use.

## Manual installation fallback

Use only the `controlel.zip` and `controlel.zip.sha256` assets from an approved
Controlel integration release.

1. Download both assets.
2. Calculate the ZIP SHA-256 and compare it with
   `controlel.zip.sha256` and the release notes.
3. Create `config/custom_components/controlel/`.
4. Extract the contents of `controlel.zip` directly into that directory.
   `manifest.json` and `__init__.py` must be directly below
   `config/custom_components/controlel/`; there must not be another
   `custom_components/controlel` directory inside it.
5. Restart Home Assistant.
6. Add Controlel through **Settings > Devices & services**.

## First configuration

The normal form asks for only the zone and sensor names, a temperature sensor,
the target temperature, and one controlled switch. The temperature selector is
restricted to `sensor` entities with temperature device class. Controlel
generates stable lowercase ASCII sensor and zone IDs from the names and does
not regenerate them after a rename.

New entries default to a 21.0 °C target, 15-minute maximum measurement age,
30-second future timestamp tolerance, 2-minute sensor-failure grace period,
and **Turn heating off — recommended** after timeout. These defaults apply only
to new entries; stored values in an existing entry are preserved exactly.

Simple mode derives these calls without asking the user for service names:

| Purpose | Domain | Service | Target |
| --- | --- | --- | --- |
| Enable heating | `switch` | `turn_on` | `switch.boiler` |
| Disable heating | `switch` | `turn_off` | `switch.boiler` |

Controlel accepts configured service names but cannot verify that a target is
physically safe. Use a dedicated entity with appropriate hardware interlocks.
Controlel cannot call its own service domain.

For equipment that is not one normal switch, select **Use custom Home
Assistant services**. Advanced settings keep separate service domains, names,
and target entities for enabling and disabling heat.

## Edit an existing entry

Open **Settings > Devices & services > Controlel > Configure**. The first
options step edits basic settings; the second edits safety, diagnostic profile,
and custom bindings. Saving options preserves the stable IDs, atomically stores
mutable settings, updates the entry title from the zone name, and reloads the
entry. Existing entries need no migration and no delete/recreate cycle.

Diagnostic profiles have stable stored values `basic`, `detailed`, and `debug`.
New 0.5.0 and later entries default to Basic. Entries upgraded from 0.4.0 or older that
have no stored profile resolve to Detailed so their periodic timing visibility
continues. This fallback is read-time compatibility behavior and does not write
migration data during setup. Saving the unchanged Options Flow stores the
resolved Detailed selection normally; an explicitly stored profile always wins.
Detailed updates active countdowns every 10 seconds. Debug updates only active
countdown entities every second and displays a Recorder-impact warning. Debug
expires after 60 minutes by default and returns to the profile that was active
before Debug; select
**Keep Debug active until manually changed** to disable expiry. Profile changes
never change control decisions or entity unique IDs.

## Operational device and diagnostics

Each entry creates one device named `Controlel — <Zone name>`. Its primary
entities show current and target temperature, heat demand, whether heat is
required, and the safety state. Diagnostic entities show measurement validity
(`valid`, `unavailable`, `unknown`, `invalid_value`, `stale`,
`future_timestamp`, or `not_received`), measurement age, grace remaining,
latest decision and reason, requested command and service-call outcome,
meaningful-event and command times, runtime state, failure flags, suppression
count, configured timings, active deadlines and remaining durations, diagnostic
profile, Debug expiry, trace capacity, and integration/core versions. Configured
durations remain available when inactive. An unavailable deadline or remaining
entity means that countdown is inactive, not that the integration failed.

These entities report Controlel's demand and requests. “Service call
dispatched” means Home Assistant accepted the blocking service call; it does
not confirm physical boiler or heat-source state. The target remains editable
through **Configure**, not through a writable dashboard entity.

Home Assistant's config-entry diagnostics download contains only normalized
configuration, version data, the immutable current operational snapshot,
entity and owned Repairs IDs, counters, and an allowlisted observability section.
The bounded in-memory trace capacity is 20/100/500 records in
Basic/Detailed/Debug. Unknown config-entry fields, credentials, arbitrary
payloads, and unrelated Home Assistant state or attributes are excluded. The
snapshot and trace are reconstructed on reload/restart and are not persistent.

## Recorder guidance

Controlel cannot rewrite the user's Recorder configuration. Detailed and Debug
can increase state-change and database volume while a countdown is active,
especially the one-second Debug remaining-duration entities. If this evidence
is not needed in history, exclude Controlel's technical `*_remaining` diagnostic
entities—particularly lockout, grace, measurement-staleness, and Debug-expiry
remaining—from Recorder using Home Assistant's supported Recorder configuration.
Configured durations, deadlines, and the operational summary can remain
recorded. This is a recommendation only; Controlel does not apply exclusions
automatically.

## Expected first setup behavior

Setup subscribes to the configured temperature entity in buffering mode,
processes its current state, drains state changes received during setup, and
then starts the control runtime. A valid fresh measurement can therefore
produce a heat-source service call immediately.

An unknown, unavailable, malformed, stale, unitless, or timestamp-less state
does not become a measurement. Demand remains indeterminate during the grace
period; after the grace period Controlel applies the configured timeout
action. Successful service return is not confirmation of physical heat-source
state. Service failures are reported through logs and Repairs and are not
retried automatically.

## Upgrade and rollback

HACS detects new versions from GitHub Releases. Download the new version and
restart Home Assistant even if a reload is offered; replacing imported Python
files in a running process is not a supported upgrade boundary.

An upgrade unloads the old runtime and reconstructs all in-memory state. It
does not restore measurements, demand, applied action, timers, or physical
heat-source state.

If a release is faulty, select an earlier available release in HACS and
restart. Published assets and tags are immutable; corrections use a higher
integration patch version. A future release that changes stored config-entry
structure must provide an explicit migration.

## Removal

1. Remove the Controlel config entry in **Settings > Devices & services**.
   This unloads and terminally stops the runtime without sending an implicit
   heat-source command and clears its owned Repairs issues.
2. In HACS, open Controlel's menu and select **Remove**.
3. Restart Home Assistant.

HACS removes the integration directory but does not uninstall Python packages
or related Home Assistant data automatically. The `controlel==0.8.0` package
may remain in Home Assistant's managed Python environment and must not be
manually removed.

## Known limitations

M31B configuration uses one modular `notifications` object in advanced options
so notification policy remains separate from heating fields. It contains an
`enabled` flag, zero or more recipients, ordinary and CRITICAL rate settings,
and bounded `history_capacity`. Each recipient has a stable `recipient_id`,
transport `home_assistant_notify`, a `notify.<service>` target, enabled flag,
minimum level (`critical`, `operational`, `detailed`, or `debug`), and optional
canonical event categories. Existing and new entries default to disabled with
no recipients. Controlel never discovers or targets notify services
automatically. Enabled recipients may not share the same transport and target.

Notifications are best-effort and in-memory. Home Assistant uses one coalesced
drain task with no polling or retry loop. Unload prevents new work but cannot
revoke a service call already accepted by Home Assistant. The future dedicated
Notifications sidebar page, recipient CRUD APIs, and test-notification APIs are
explicitly deferred.

- One config entry, one zone, one primary sensor, and one heat source.
- No persistence across reload or restart.
- No service-call retry.
- No physical-state confirmation.
- No discovery, multi-zone UI, writable operational entities, or generic
  service data.
- No persistent decision history; diagnostics expose only the bounded
  in-memory trace.
- Custom-repository distribution only; no default HACS-store claim.

See [Troubleshooting](Troubleshooting.md) for failure diagnosis.
