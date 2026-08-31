# Controlel UI and configuration layers

Controlel development is organized into four distinct layers. Each layer has a
single responsibility; do not mix configuration authority, observability, or
guided setup in the same surface.

## Layers

| # | Layer | Role | Status |
|---|--------|------|--------|
| 1 | **Native HA Configuration** | Authoritative configuration surface (`config_flow.py`, canonical v3 drafts, activation) | Production |
| 2 | **Controlel Observability UI** | Read-only module, config summary, runtime and diagnostics presentation (Home Assistant panel) | Current panel scope |
| 3 | **Controlel Configuration UI** | Future direct editing through the same backend as HA Configure | Planned |
| 4 | **Controlel Guided Setup / Wizard** | Future guided UX over the same backend | Experimental (code retained, hidden from primary navigation) |

The Home Assistant panel (`custom_components/controlel/frontend/`) implements
**layer 2 only**. It consumes Frontend API v1 read projections. It does not
activate revisions, mutate canonical drafts, or issue runtime control commands.

When configuration is required, the panel directs users to **Settings → Devices
& services → Controlel → Configure** in Home Assistant.

## Required development order for every new module

Follow this sequence for each new Controlel module. Do not skip layers or imply
readiness where configuration does not exist.

```text
Core / domain
  → Native HA Configuration
  → real HAOS validation
  → Observability UI
  → direct Configuration UI
  → Guided Setup / Wizard
```

1. **Core / domain** — models, safety, explicit state, tests.
2. **Native HA Configuration** — config flow entries, canonical scopes, activation contract.
3. **real HAOS validation** — exercise on a real Home Assistant OS instance before UI work.
4. **Observability UI** — read-only Frontend API projections and truthful module states.
5. **direct Configuration UI** — in-panel editing reusing the HA Configure backend.
6. **Guided Setup / Wizard** — optional guided UX on top of the same backend.

## Module presentation states (Observability UI)

The Observability UI uses explicit labels only:

- **Not configured** — module has never been configured (`*_not_configured` reason).
- **Draft incomplete** — configured heating with setup readiness `incomplete` or `invalid`.
- **Draft ready** — configured heating with setup readiness `ready` but module not yet active.
- **Active** — module `status: active`.
- **Disabled** — explicit disable reason (e.g. `water_safety_disabled`); never used for never-configured Water Safety.
- **Degraded** — runtime degradation or inactive without a clearer draft state.
- **Error** — module `status: error` with a fault reason.

Setup readiness refines heating presentation only when the module is already
known to be configured. Readiness alone never implies a module is configured.

## Related documents

- [Frontend API v1](FrontendAPI.md) — read contract for the Observability UI
- [AGENTS.md](../../AGENTS.md) — truthfulness and layer separation rules
- [frontend/README.md](../../custom_components/controlel/frontend/README.md) — panel implementation notes
