# Home Assistant installation

Controlel `0.3.0` is the current development candidate for one heating zone,
one primary temperature sensor, and one shared heat source. It requires the
public core package `controlel==0.1.0`.

Candidate `0.3.0` is not published; use the latest published release for HACS
custom-repository installation. Controlel is not listed in the default HACS
store.

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
Assistant reads the manifest and installs `controlel==0.1.0` from PyPI.
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
options step edits basic settings; the second edits safety values and custom
bindings. Saving options preserves the stable IDs, atomically stores mutable
settings, updates the entry title from the zone name, and reloads the entry.
Existing `0.1.1` entries need no migration and no delete/recreate cycle.

## Operational device and diagnostics

Each entry creates one device named `Controlel — <Zone name>`. Its primary
entities show current and target temperature, heat demand, whether heat is
required, and the safety state. Diagnostic entities show measurement validity
(`valid`, `unavailable`, `unknown`, `invalid_value`, `stale`,
`future_timestamp`, or `not_received`), measurement age, grace remaining,
latest decision and reason, requested command and service-call outcome,
meaningful-event and command times, runtime state, failure flags, suppression
count, and integration/core versions. Age and grace countdowns refresh every
30 seconds as well as on runtime events.

These entities report Controlel's demand and requests. “Service call
dispatched” means Home Assistant accepted the blocking service call; it does
not confirm physical boiler or heat-source state. The target remains editable
through **Configure**, not through a writable dashboard entity.

Home Assistant's config-entry diagnostics download contains only normalized
configuration, version data, the immutable current operational snapshot,
entity and owned Repairs IDs, counters, and at most 20 recent in-memory
decision records. Unknown config-entry fields and unrelated Home Assistant
state or attributes are excluded. The snapshot and trace are reconstructed on
reload/restart and are not persistent.

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
or related Home Assistant data automatically. The `controlel==0.1.0` package
may remain in Home Assistant's managed Python environment and must not be
manually removed.

## Known limitations

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
