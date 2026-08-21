# Controlel Setup Wizard — Frontend Prototype

A small, self-contained prototype of the Controlel heating setup wizard.
It is a **design/UX prototype only**: mock data, no backend calls, no build
step.

## Run

Open `index.html` directly in a browser, or serve the folder:

```bash
python -m http.server 8000
# then open http://localhost:8000
```

## Scope

- 4 steps: discovery summary → zone → sensor & heat source → review & validation.
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

## Files

| File | Purpose |
| --- | --- |
| `index.html` | Page shell |
| `styles.css` | Prototype styling |
| `mock-data.js` | Mock discovery snapshot + role recommendations |
| `components.js` | Reusable stateless UI components (`CW.*`) |
| `wizard.js` | Wizard state, validation, step rendering, actions |

## Non-goals

This prototype does not implement the setup application services, draft
persistence, canonical revisions, or activation. Draft state is in-memory and
lost on reload. See `docs/architecture/09_Setup_Discovery_and_Import.md` for
the real lifecycle this UI would eventually be a client of.
