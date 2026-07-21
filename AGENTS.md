# Controlel Development Instructions

## Project

Controlel is a local-first, modular and event-driven regulation platform.

The repository root is the directory containing `.git`, `pyproject.toml`, `src`, `tests` and `docs`.

## Architecture

Maintain these layers:

- `src/controlel/domain`
  - Pure domain models and business rules.
  - Must not depend on Home Assistant, MQTT, databases, HTTP or hardware integrations.

- `src/controlel/application`
  - Use cases, orchestration, handlers, runtime, event bus and interfaces.

- `src/controlel/infrastructure`
  - External integrations, providers, persistence and hardware adapters.

Keep these concepts separate:

- Measurement = observed value.
- ControlContext = prepared regulation inputs.
- Decision = what should happen and why.
- Event = something that happened.
- Command = executable requested action.
- Provider or adapter = communication with the outside world.

The canonical Sensor model is:

`src/controlel/domain/sensors/sensor.py`

The canonical SensorId model is:

`src/controlel/domain/value_objects/sensor_id.py`

Do not create duplicate domain models in other folders.

## Working method

Before editing:

1. Read relevant implementation and tests.
2. Run `git status`.
3. Run `pytest` to establish the baseline.
4. Search all usages before changing a public model or constructor.
5. Do not guess file paths or class locations.

While editing:

1. Make the smallest coherent change.
2. Do not perform unrelated refactors.
3. Preserve existing contracts unless the task explicitly changes them.
4. If a contract changes, update all affected usages and tests consistently.
5. Do not add compatibility behavior merely to satisfy obsolete tests without first identifying the authoritative contract.
6. Never duplicate a model to fix an import error.

After editing run:

```powershell
pytest
ruff check .
ruff format --check .
pre-commit run --all-files
