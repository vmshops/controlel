# Controlel Frontend

This directory contains the dependency-free Home Assistant panel and its
development/demo harness. The production panel uses Home Assistant's
authenticated WebSocket connection for read-only Frontend API v1 projections
and Setup Write API v1 draft/validation operations. Mock data is never used by
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
| `heating` | Zone, reported temperature, target, demand state, heat source permission state, status/reason, configuration completeness, recent events |
| `diagnostics` | Readable activity list with Basic / Detailed / Debug display levels; reason codes and raw metadata behind expandable Details |
| `settings` | Settings overview (navigation/structure only, not a settings form) |
| `setup` | Real discovery, resumable draft editing, and backend validation |

Navigation is hash-based (`#/route`), so deep links and back/forward work.

## Setup wizard

The wizard is a 4-step flow: real discovery → zone → sensor & heat-source
targets → review and backend validation.

- Discovery and recommendations come from the existing `SetupHostService`
  through the authenticated HA transport.
- Recommended and Alternative candidates preserve backend confidence and
  reason codes.
- Important bindings (primary temperature sensor, heat source) require
  explicit confirmation; switching candidates resets the confirmation.
- **Save and finish later** creates the next persisted draft revision.
- The browser stores only the draft identifier needed to request a backend
  reopen; the backend draft remains authoritative.
- Validation messages and readiness are returned by the backend for the exact
  persisted revision. Backend failures remain explicit errors.
- No activate, canonicalize, runtime-control, or HA device-service action is
  exposed by the wizard client.

An incomplete Heating module surfaces **Continue setup** actions (Overview,
Modules, Heating, Settings) that open the wizard. Starting discovery reopens a
known persisted draft or creates a new incomplete backend draft.

## Files

| File | Purpose |
| --- | --- |
| `ha-panel.js` | Home Assistant panel entrypoint; loads production runtime assets only |
| `api-client.js` | Authenticated Frontend API v1 and setup-only draft client/adapters |
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
real setup request mapping, discovery response rendering, draft
create/reopen/update/validate, explicit backend errors, no mock fallback, and
absence of activation/runtime calls.

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

This milestone does not activate configuration, change active configuration,
control devices, or alter runtime heating behavior. Canonicalization and
activation remain outside the frontend setup client.
