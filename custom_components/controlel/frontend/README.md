# Controlel Frontend

This directory contains the dependency-free Home Assistant panel and its
development/demo harness. The production panel uses Home Assistant's
authenticated WebSocket connection for read-only Frontend API v1 projections,
read-only setup discovery, and Canonical configuration v3 lifecycle operations. Mock data is never used by
the setup wizard and is not packaged in the HACS release.

## Run

Open `index.html` directly in a browser, or serve the folder:

```bash
python -m http.server 8000
# then open http://localhost:8000            → application shell
#       http://localhost:8000/wizard.html    → standalone setup wizard
```

## Views

| Route (`#/…`) | View |
| --- | --- |
| `overview` (default) | Overall status, module states, important warnings, quick actions |
| `modules` | Module cards: Heating (configured/incomplete), Smart Charging, Lighting, Water Safety (not configured / coming later) |
| `heating` | Active canonical-v3 revision and single-zone settings editor, plus separate operational zone, demand and heat-source evidence |
| `diagnostics` | Readable activity list with Basic / Detailed / Debug display levels; reason codes and raw metadata behind expandable Details |
| `settings` | Shared canonical-v3 Heating summary/editor plus frontend-local and placeholder settings |
| `setup` | Real discovery, resumable draft editing, and backend validation |

Navigation is hash-based (`#/route`), so deep links and back/forward work.

## Setup wizard

The wizard is a 5-step flow: real discovery → zone → sensor & heat-source
targets → heating settings → review and canonical-v3 lifecycle actions.

- Discovery and recommendations come from the existing `SetupHostService`
  through the authenticated HA transport.
- Recommended and Alternative candidates preserve backend confidence and
  reason codes.
- Important bindings (primary temperature sensor, heat source) require
  explicit confirmation; switching candidates resets the confirmation.
- **Save Draft** creates or updates the same canonical-v3 draft surface used by
  native Home Assistant Configure. A greenfield draft is first persisted only
  after required stable bindings have been explicitly confirmed.
- The browser stores only the draft identifier needed to request a backend
  reopen; the backend draft remains authoritative.
- Validation evidence applies to one exact persisted revision. Canonicalize
  creates an immutable candidate but does not activate it; Activate remains a
  separate protected backend transition. Backend failures remain explicit.
- No runtime-control or HA device-service action is exposed by the wizard.

An incomplete Heating module surfaces **Continue setup** actions (Overview,
Modules and Heating) that open the wizard. Starting discovery reopens a
known persisted canonical-v3 draft or clones active canonical-v3 authority for editing.

## Heating settings

Heating and Settings project the same active canonical-v3 authority used by
the Setup Wizard and native Home Assistant Configure. The projection displays
the active revision/generation, stable single-zone bindings, and the existing
compact set of typed Heating values with explicit Celsius/seconds units.

**Edit configuration** reopens a compatible persisted draft or clones the
active revision into a new draft. It never changes active authority directly.
Save Draft, Validate, Canonicalize, and Activate remain separate backend
transitions. Stable Controlel identities, runtime evidence, and deferred
physical-operation fields are preserved but are not editable on this surface.

## Files

| File | Purpose |
| --- | --- |
| `ha-panel.js` | Home Assistant panel entrypoint; loads production runtime assets only |
| `api-client.js` | Authenticated Frontend API v1, setup discovery, and canonical-v3 lifecycle adapters |
| `i18n.js` | English/Czech localization foundation |
| `index.html` | Application shell entry (all views + hosted wizard) |
| `wizard.html` | Standalone setup wizard page (original entry point) |
| `styles.css` | Prototype styling (wizard + app shell) |
| `mock-data.js` | Legacy isolated setup fixture; never loaded by the real wizard path |
| `mock-app-data.js` | Mock app state: modules, heating overview, activity, settings |
| `components.js` | Reusable stateless UI components (`CW.*`) |
| `wizard.js` | Real discovery, resumable draft state, backend validation, and step rendering |
| `app.js` | App shell: routing, views, mock-data rendering (`CA.*`) |
| `tests/dom-stub.js` | Minimal DOM stub for Node-based tests |
| `tests/app.test.js` | Behavior tests (navigation, module status, Continue setup, diagnostics filtering, components, wizard) |

The HACS archive includes `ha-panel.js`, `app.js`, `api-client.js`,
`components.js`, `i18n.js`, `wizard.js`, and `styles.css`. It excludes the
standalone HTML, README, Node tests, and mock datasets.

## Tests

Behavior tests run in Node with no external dependencies:

```bash
node --test tests/*.test.js
```

Covered: navigation and route fallback, module states, diagnostics filtering,
real setup request mapping, discovery response rendering, cross-surface draft
resume, active Heating projection, canonical create/edit/update/validate/
canonicalize/activate boundaries, explicit backend errors, and no mock fallback.

## Architecture notes

- **Mock-data boundary**: mock files are development-only and never ship in
  the HACS artifact. The wizard does not import them. Real request failures
  remain explicit errors or disconnected states.
- **Truthfulness**: temperatures are sensor *reports*, the heat source state
  is a *permission* state, and unknown stays unknown. A successful command is
  never rendered as physical confirmation.
- **Future customization**: navigation items, modules and settings rows are
  plain data objects with `{id, label, order, hidden}`, and rendering always
  goes through `CA.visibleItems()`. This prepares hide/show, reorder and
  label overrides without a layout schema or drag-and-drop (both deferred).

## Non-goals

The Wizard supports the existing protected canonical-v3 activation lifecycle.
It does not directly control devices, infer physical operation, implement
multi-zone configuration, or bypass backend validation and source safety.
