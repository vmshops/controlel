# Controlel Frontend

This directory contains the dependency-free Home Assistant read-only panel and
its development/demo harness. The production panel uses Home Assistant's
authenticated WebSocket connection and Frontend API v1. Mock data is available
only through the standalone development pages and is not packaged in the HACS
release.

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
| `setup` | The existing setup wizard (unchanged behavior) |

Navigation is hash-based (`#/route`), so deep links and back/forward work.

## Setup wizard (preserved)

The wizard is the same 4-step flow as before: discovery summary → zone →
sensor & heat source → review & validation.

- Recommended and Alternative candidates with confidence and reason codes.
- Important bindings (primary temperature sensor, heat source) require
  explicit confirmation; switching candidates resets the confirmation.
- **Save and finish later** is always available, even for incomplete drafts.
- The header always shows whether setup is **Complete** or **Incomplete** and
  how many blocking items remain.
- The primary action is always pressable: **Check readiness** when incomplete
  (shows a blocking-item summary with links that jump to the relevant step),
  and **Activate** when all blocking items are resolved (performs the mock
  activation). An incomplete setup can never become active.
- Deterministic validation with stable reason codes
  (`ZONE_REQUIRED`, `SENSOR_CONFIRMATION_REQUIRED`, `SENSOR_AREA_MISMATCH`, …).

An incomplete Heating module surfaces **Continue setup** actions (Overview,
Modules, Heating, Settings) that open the wizard without restarting it from
step 1 — the draft state is kept in memory for the page session.

## Files

| File | Purpose |
| --- | --- |
| `ha-panel.js` | Home Assistant panel entrypoint; loads production runtime assets only |
| `api-client.js` | Authenticated read-only Frontend API v1 client and data adapter |
| `i18n.js` | English/Czech localization foundation |
| `index.html` | Application shell entry (all views + hosted wizard) |
| `wizard.html` | Standalone setup wizard page (original entry point) |
| `styles.css` | Prototype styling (wizard + app shell) |
| `mock-data.js` | Mock discovery snapshot + role recommendations (wizard) |
| `mock-app-data.js` | Mock app state: modules, heating overview, activity, settings |
| `components.js` | Reusable stateless UI components (`CW.*`) |
| `wizard.js` | Wizard state, validation, step rendering, actions (unchanged) |
| `app.js` | App shell: routing, views, mock-data rendering (`CA.*`) |
| `tests/dom-stub.js` | Minimal DOM stub for Node-based tests |
| `tests/app.test.js` | Behavior tests (navigation, module status, Continue setup, diagnostics filtering, components, wizard) |

The HACS archive includes `ha-panel.js`, `app.js`, `api-client.js`,
`components.js`, `i18n.js`, and `styles.css`. It excludes the standalone HTML,
README, Node tests, prototype wizard, and mock datasets.

## Tests

Behavior tests run in Node with no external dependencies:

```bash
node --test tests/app.test.js
```

Covered: navigation and route fallback, module status rendering for all
states, incomplete Heating → Continue setup, diagnostics level filtering,
reusable component rendering, and preserved wizard behavior (steps, footer
actions, incomplete draft cannot activate).

## Architecture notes

- **Mock-data boundary**: all mock backend state lives in `mock-data.js` and
  `mock-app-data.js`. These files are development-only and never ship in the
  HACS artifact. Real request failures remain explicit errors or disconnected
  states; they never select mock data.
- **Truthfulness**: temperatures are sensor *reports*, the heat source state
  is a *permission* state, and unknown stays unknown. A successful command is
  never rendered as physical confirmation.
- **Future customization**: navigation items, modules and settings rows are
  plain data objects with `{id, label, order, hidden}`, and rendering always
  goes through `CA.visibleItems()`. This prepares hide/show, reorder and
  label overrides without a layout schema or drag-and-drop (both deferred).

## Non-goals

This prototype does not implement the setup application services, draft
persistence, canonical revisions, or activation. Draft state is in-memory and
lost on reload. See `docs/architecture/09_Setup_Discovery_and_Import.md` for
the real lifecycle this UI would eventually be a client of.
