# Home Assistant installation

Controlel `0.1.1` is a custom Home Assistant integration for one heating zone,
one primary temperature sensor, and one shared heat source. It requires the
public core package `controlel==0.1.0`.

The repository is prepared for a controlled HACS custom-repository release,
but no integration release is published yet. Controlel is not listed in the
default HACS store.

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

After an integration release is published:

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

The config flow stores one immutable configuration:

- **Sensor ID**: Controlel's stable identifier for the sensor.
- **Sensor name**: Human-readable sensor name.
- **Temperature entity**: Home Assistant temperature sensor entity.
- **Zone ID** and **Zone name**: Stable and display names for the zone.
- **Target temperature**: Desired zone temperature in Celsius.
- **Primary measurement maximum age**: Maximum accepted age of the primary
  measurement.
- **Maximum future clock skew**: Tolerance for a measurement timestamp ahead
  of Home Assistant's clock.
- **Indeterminate grace period**: How long missing or stale evidence is
  tolerated before applying the configured safety action.
- **Timeout action**: Enable or disable heating after the grace period.
- **Enable/disable service domain, name, and target entity**: Exact Home
  Assistant calls used to control the heat source.

Example for a dedicated boiler switch:

| Purpose | Domain | Service | Target |
| --- | --- | --- | --- |
| Enable heating | `switch` | `turn_on` | `switch.boiler` |
| Disable heating | `switch` | `turn_off` | `switch.boiler` |

Controlel accepts configured service names but cannot verify that a target is
physically safe. Use a dedicated entity with appropriate hardware interlocks.
Controlel cannot call its own service domain.

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
- No options or reconfigure flow.
- No persistence across reload or restart.
- No service-call retry.
- No physical-state confirmation.
- No discovery, polling, diagnostic entities, multi-zone UI, or generic
  service data.
- Custom-repository distribution only; no default HACS-store claim.

See [Troubleshooting](Troubleshooting.md) for failure diagnosis.
