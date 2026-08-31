# Controlel Frontend

This directory contains the dependency-free Home Assistant panel and its
development/demo harness. The production panel is **layer 2 — Observability
UI**: read-only Frontend API v1 projections and configuration summaries.
Configuration writes belong in native Home Assistant Configure (layer 1).
Mock data is never used silently and is not packaged in the HACS release.

See [UILayers.md](../../../docs/architecture/UILayers.md) for the four UI
layers and required module development order.

## Run

Open `index.html` directly in a browser, or serve the folder:

```bash
python -m http.server 8000
# then open http://localhost:8000            → application shell
#       http://localhost:8000/wizard.html    → standalone setup wizard (dev)
```

## Views (primary navigation)

| Route (`#/…`) | View |
| --- | --- |
| `overview` (default) | Overall status, module states, important warnings, quick actions |
| `modules` | Heating and Water Safety module cards with truthful states |
| `heating` | Read-only canonical summary, operational zone/demand and heat-source evidence |
| `water-safety` | Moisture assessment, incidents (read-only; no runtime actions) |
| `diagnostics` | Activity list with Basic / Detailed / Debug levels |
| `settings` | Configuration summary rows and frontend-local preferences |

Navigation is hash-based (`#/route`). The **Setup / Wizard** route (`#/setup`)
remains in the codebase for experimental/developer use (Settings → Advanced) but
is hidden from primary navigation.

## Observability constraints

- No Save, Activate, Edit, or water-safety runtime actions in normal UI.
- Where configuration is needed, **Configure in Home Assistant** is shown.
- Module states: Not configured, Draft incomplete, Draft ready, Active,
  Disabled, Degraded, Error — never infer configured from readiness alone.

## Experimental Setup Wizard

`wizard.js` and `water-wizard.js` are retained for development. Reach them via
`#/setup` or Settings → Advanced → Experimental Setup Wizard. Production
configuration should use Home Assistant Configure.

## Files

| File | Purpose |
| --- | --- |
| `ha-panel.js` | Home Assistant panel entrypoint |
| `api-client.js` | Frontend API v1 and canonical read adapters |
| `app.js` | App shell: routing, read-only views (`CA.*`) |
| `components.js` | Reusable UI components (`CW.*`) |
| `i18n.js` | English/Czech localization |
| `wizard.js` / `water-wizard.js` | Experimental guided setup (not primary nav) |
| `tests/*.test.js` | Node behavior tests |

## Tests

```bash
node --test tests/*.test.js
```

Write/lifecycle tests pass `observabilityMode: false` to `createApp`. Default
bootstrap uses observability (read-only) mode.

## Non-goals (Observability UI)

- No in-panel configuration writes or activation
- No runtime device control from the panel
- No redesign beyond navigation clarity
