# Controlel Home Assistant / HACS Readiness Audit

**Date:** 2026-08-24  
**Branch:** `audit/ha-hacs-quality-readiness`  
**Commit:** `58245bf`  
**Scope:** Home Assistant integration and HACS distribution readiness  
**Method:** Read-only evidence-based review of repository artifacts

---

## Executive Summary

The Controlel Home Assistant integration is **structurally sound and well-tested**. The integration follows Home Assistant best practices for config flow, diagnostics, panel registration, and lifecycle management. The HACS build/validator pipeline is deterministic, comprehensive, and tested. The frontend is read-only, truthful, and well-structured with i18n support (en/cs) and 77 passing behavior tests.

**One BLOCKED item** prevents publication: the integration imports `controlel.frontend_api.v1` from Core, but the published Core 0.12.0 does not include Frontend API v1. This is a known release dependency pending Core 0.13.0 publication.

**One actionable finding** requires attention before release: the release documentation (ReleaseGuide.md, home-assistant-0.12.0.md, releases.yaml) describes HA 0.12.0 as "not including frontend transport/UI," but the current 0.12.0 tree does include the frontend panel and Frontend API v1 transport. This is a release metadata inconsistency that should be resolved before tagging.

---

## Scope and Methodology

This audit reviewed the following artifacts in the `controlel-qwen-hacs-audit` worktree (branch `audit/ha-hacs-quality-readiness`, commit `58245bf`):

- `custom_components/controlel/` — integration source
- `hacs.json` — HACS manifest
- `manifest.json` — HA integration manifest
- `strings.json` / `translations/en.json` — localization
- `config_flow.py` — config and options flow
- `diagnostics.py` — diagnostics
- `__init__.py` — setup/unload/reload lifecycle
- `panel.py` — frontend panel registration
- `frontend/` — frontend assets and tests
- `scripts/packaging/` — HACS build/validator
- `tests/integrations/home_assistant/` — integration tests
- `tests/packaging/` — packaging tests
- `.github/workflows/` — CI workflows
- `release-metadata/` — release metadata
- `docs/releases/` — release documentation
- `docs/development/` — development guides

**Verification performed:**
- Frontend behavior tests: `node --test tests/app.test.js tests/api-client.test.js tests/i18n.test.js` → **77 passed, 0 failed**
- HACS build: `python scripts/packaging/build_hacs_release.py --version 0.12.0` → **success**
- HACS validation: `python scripts/packaging/validate_hacs_release.py` → **success**
- Archive inspection: 37 files, correct file set, no dev-only files

---

## Findings

### 1. HACS Manifest (`hacs.json`)

**Status:** PASS

**Evidence:**
```json
{
  "name": "Controlel",
  "zip_release": true,
  "filename": "controlel.zip",
  "hide_default_branch": true,
  "homeassistant": "2026.7.3"
}
```

**Assessment:** Correct and complete. The `homeassistant` version (2026.7.3) matches the test environment (`requirements/ha-test.txt` pins `homeassistant==2026.7.3`). The `zip_release` and `filename` fields are appropriate for a HACS zip release. `hide_default_branch` is set to prevent accidental installation from the default branch.

---

### 2. HA Integration Manifest (`manifest.json`)

**Status:** PASS

**Evidence:**
```json
{
  "domain": "controlel",
  "name": "Controlel",
  "codeowners": ["@vmshops"],
  "config_flow": true,
  "documentation": "https://github.com/vmshops/controlel",
  "integration_type": "hub",
  "iot_class": "local_push",
  "issue_tracker": "https://github.com/vmshops/controlel/issues",
  "requirements": ["controlel==0.12.0"],
  "single_config_entry": true,
  "version": "0.12.0"
}
```

**Assessment:** Correct and complete. All required fields are present. The `requirements` field pins exactly `controlel==0.12.0` (no range specifiers). `single_config_entry` is appropriate for a single-zone heating control integration. `iot_class: local_push` is correct for a local integration that pushes state changes.

**Note:** The `requirements` pin to `controlel==0.12.0` is the source of the BLOCKED finding (see Finding 12).

---

### 3. Localization (`strings.json` / `translations/en.json`)

**Status:** PASS

**Evidence:**
- `strings.json` and `translations/en.json` are **identical** (verified with `diff`).
- Both files contain all required sections: `title`, `config`, `options`, `entity`, `issues`.
- The `config` section includes `step.user`, `step.advanced`, and `error` with comprehensive data labels and descriptions.
- The `entity` section includes sensor and binary_sensor translations with state mappings.
- The `issues` section includes `heat_source_service_failure` and `fatal_runtime_failure` with title and description.

**Assessment:** Complete and well-structured. The translations are truthful and action-oriented (e.g., "Heating permission was enabled" rather than "Heating is on"). The `data_description` fields provide helpful context for each configuration option.

---

### 4. Config Flow (`config_flow.py`)

**Status:** PASS

**Evidence:**
- `ControlelConfigFlow` implements `async_step_user` and `async_step_advanced`.
- `ControlelOptionsFlow` implements `async_step_init` and `async_step_advanced`.
- No `async_step_reconfigure` (verified by test `test_config_flow_exposes_supported_options_flow_without_reconfigure_flow`).
- Comprehensive validation: `_validate_basic`, `_configuration_errors`, `_validate_identifier`.
- Entity selectors with appropriate filters (temperature sensor, switch, climate).
- Number selectors with min/max constraints and units.
- Select selectors for control mode, heat delivery mode, ownership, assist policy.
- Advanced settings include safety times, diagnostic profile, and custom service bindings.

**Assessment:** Well-structured and comprehensive. The flow separates basic and advanced settings, provides helpful descriptions, and validates all inputs. The options flow preserves stable IDs while allowing mutable settings to be edited.

---

### 5. Diagnostics (`diagnostics.py`)

**Status:** PASS

**Evidence:**
- `async_get_config_entry_diagnostics` returns a comprehensive diagnostics payload.
- Includes: `configuration`, `configuration_provenance`, `versions`, `operational_snapshot`, `decision_trace`, `observability`, `heat_delivery`, `heating_diagnostics`, `runtime_supervision`, `operational_events`, `user_activities`, `notification_policy`, `source_resilience`, `counters`, `entity_ids`, `active_issue_ids`.
- Privacy-minimized: uses allowlists (`_RAW_ALLOWLIST`, `_MUTABLE_ALLOWLIST`) to control which configuration values are exposed.
- Notification policy diagnostics include recipient count and transport but not raw recipient targets.
- Handles unloaded state gracefully (returns `runtime: {status: "unloaded"}`).

**Assessment:** Comprehensive and privacy-aware. The diagnostics provide sufficient detail for troubleshooting while minimizing exposure of sensitive configuration. The allowlist approach is appropriate.

---

### 6. Setup/Unload/Reload Lifecycle (`__init__.py`)

**Status:** PASS

**Evidence:**
- `async_setup_entry` constructs the runtime, registers the frontend API, forwards platform setups, and registers the panel.
- `async_unload_entry` unloads platforms, unregisters the frontend API, stops the host, and removes the panel.
- `async_remove_entry` clears repairs issues for the deleted config entry.
- `_async_update_listener` reloads the entry after an atomic options change.
- Panel registration failure is **non-fatal** (logged and caught).
- Frontend API registration is idempotent (stale-safe cleanup).
- Error handling: partial construction failures are cleaned up (host stopped, executor closed).

**Assessment:** Well-structured and robust. The lifecycle is explicit and deterministic. Panel registration failure does not prevent the core integration from functioning. The frontend API registry supports multiple entries and stale-safe cleanup.

---

### 7. Panel Registration (`panel.py`)

**Status:** PASS

**Evidence:**
- `async_register_controlel_panel` registers a static path and a sidebar panel.
- Idempotent: static path registered once per process, panel only registered if not already present.
- `async_remove_controlel_panel` removes the panel (idempotent).
- Panel uses `panel_custom.async_register_panel` with `module_url` (standard custom-integration pattern).
- Panel is read-only: reuses the existing Frontend API v1 WebSocket transport and authenticated HA connection.
- No new endpoints, control actions, or authentication introduced.

**Assessment:** Correct and safe. The panel follows the standard HA custom-panel pattern. It is read-only and does not introduce new security surface. The idempotent registration prevents duplicate panels on reload.

---

### 8. Frontend Assets (`frontend/`)

**Status:** PASS

**Evidence:**
- 12 files: `ha-panel.js`, `app.js`, `api-client.js`, `components.js`, `wizard.js`, `i18n.js`, `mock-data.js`, `mock-app-data.js`, `styles.css`, `index.html`, `wizard.html`, `README.md`.
- `ha-panel.js` is the panel entrypoint (thin adapter that builds the shell DOM and loads scripts).
- `api-client.js` is the only module that talks to the backend (uses `window.hass.connection`).
- `app.js` renders views from the Frontend API v1 adapter.
- `i18n.js` provides en/cs translations with fallback to English.
- `mock-data.js` and `mock-app-data.js` are for demo mode only (never a silent fallback for failed real requests).
- `index.html` and `wizard.html` are dev-only (excluded from HACS release).
- `tests/` contains Node-based behavior tests (excluded from HACS release).

**Verification:**
- `node --test tests/app.test.js tests/api-client.test.js tests/i18n.test.js` → **77 passed, 0 failed**

**Assessment:** Well-structured and truthful. The frontend is read-only, uses the existing authenticated HA connection, and never silently falls back to mock data. The i18n layer is dependency-free and supports en/cs. The behavior tests are comprehensive.

---

### 9. HACS Build/Validator (`scripts/packaging/`)

**Status:** PASS

**Evidence:**
- `build_hacs_release.py` builds a deterministic ZIP archive (fixed timestamp, fixed mode, sorted file order).
- `validate_hacs_release.py` validates:
  - Source file set matches `EXPECTED_ARCHIVE_FILES` (37 files).
  - Dev-only files are excluded (`index.html`, `wizard.html`, `README.md`, `tests/`).
  - `hacs.json` matches `EXPECTED_HACS_MANIFEST`.
  - `manifest.json` matches expected metadata (domain, documentation, issue_tracker, requirements, version).
  - `INTEGRATION_VERSION` in `const.py` matches the release version.
  - `strings.json` and `translations/en.json` are identical and contain required sections.
  - No secret-like content (private keys, AWS keys, GitHub tokens).
  - Archive paths are safe (no traversal, no symlinks, no duplicates).
  - Archive timestamps and modes are deterministic.

**Verification:**
- `python scripts/packaging/build_hacs_release.py --version 0.12.0` → **success**
- `python scripts/packaging/validate_hacs_release.py` → **success**
- Archive contains 37 files, correct file set, no dev-only files.

**Assessment:** Comprehensive and deterministic. The build/validator pipeline is well-tested and prevents common HACS release errors (wrong file set, secret leakage, non-deterministic archives).

---

### 10. Integration Tests (`tests/integrations/home_assistant/`)

**Status:** PASS

**Evidence:**
- 14 test files covering:
  - `test_config_flow.py` — config and options flow
  - `test_setup_and_unload.py` — setup, unload, and state ingestion
  - `test_shutdown_and_reload.py` — shutdown and reload lifecycle
  - `test_panel.py` — panel registration, unload, reload idempotency
  - `test_repairs.py` — repairs registry (recoverable and fatal issues)
  - `test_frontend_api_v1.py` — Frontend API v1 transport and evidence
  - `test_manifest.py` — manifest and core package composition
  - `test_operational_entities.py` — operational entities
  - `test_heat_source_service.py` — heat source service calls
  - `test_fatal_scheduled_failures.py` — fatal failure handling
  - `test_scheduler.py` — scheduler behavior
  - `test_state_ingestion.py` — state ingestion
  - `test_config.py` — configuration
  - `test_entity_reference.py` — entity references

**Assessment:** Comprehensive and thorough. The tests cover the full lifecycle (setup, unload, reload, shutdown), panel behavior, repairs, Frontend API v1, and core package composition. The tests use the real HA loader and fixtures.

---

### 11. CI Workflows (`.github/workflows/`)

**Status:** PASS

**Evidence:**
- `tests.yml` — runs core, packaging, and HA tests (public core composition).
- `hassfest.yml` — runs hassfest validation.
- `integration-release-validation.yml` — builds and validates the HACS release, runs HACS action and hassfest.
- `packaging.yml` — builds and validates the core package (wheel, sdist).

**Assessment:** Complete and appropriate. The CI workflows cover all necessary validation steps. The `integration-release-validation.yml` workflow is validation-only (no publishing) and uploads inspection artifacts.

---

### 12. Core 0.12.0 Public Composition

**Status:** BLOCKED

**Evidence:**
- `custom_components/controlel/frontend_api_websocket.py` line 12: `from controlel.frontend_api.v1 import FrontendApiProviderV1, frontend_response_to_dict`
- `custom_components/controlel/frontend_api.py` line 15: `from controlel.frontend_api.v1 import (BuildingEvidenceV1, ...)`
- `src/controlel/frontend_api/v1/` exists in the repository (development source).
- AGENTS.md: "Published Core 0.12.0 does not contain Frontend API v1. A failure of the public-composition tests for that specific reason is a known release dependency pending Core 0.13.0."

**Impact:** The integration cannot be installed from HACS with the published Core 0.12.0 because the `controlel.frontend_api.v1` module does not exist in the public package. The HA framework tests that verify public core composition will fail.

**Smallest fix:** Publish Core 0.13.0 with Frontend API v1, then update the integration manifest to pin `controlel==0.13.0`.

**Who should fix:** Codex/release review (Core publication is a release decision, not a code fix).

---

### 13. Release Documentation Consistency

**Status:** FAIL

**Evidence:**
- `docs/releases/home-assistant-0.12.0.md`: "No frontend UI or frontend transport is included."
- `release-metadata/releases.yaml` (HA 0.12.0 entry): "No frontend transport/UI or runtime activation is included."
- `docs/development/ReleaseGuide.md`: "Legacy conversion, frontend transport/UI, and runtime activation are separate future changes."
- **Current tree (version 0.12.0) includes:**
  - `custom_components/controlel/frontend/` (panel assets)
  - `custom_components/controlel/panel.py` (panel registration)
  - `custom_components/controlel/frontend_api.py` (Frontend API v1 provider)
  - `custom_components/controlel/frontend_api_websocket.py` (WebSocket transport)

**Impact:** The release documentation describes 0.12.0 as not including the frontend, but the current 0.12.0 tree does include it. This is a release metadata inconsistency that could confuse users and reviewers.

**Smallest fix:** Either (a) bump the integration version to 0.13.0 to reflect the new frontend, or (b) update the release documentation to accurately describe the 0.12.0 scope.

**Who should fix:** Qwen can safely update the release documentation. Version bumping is a release decision (Codex/release review preferred).

---

### 14. HACS Branding

**Status:** PASS (with note)

**Evidence:**
- No `brands/` folder in `custom_components/controlel/` or `custom_components/`.
- `.github/workflows/integration-release-validation.yml`: `ignore: brands` (HACS action will not fail due to missing brands).

**Impact:** The integration will use the default HA icon in the UI. This is a minor cosmetic issue, not a functional problem.

**Smallest fix:** (Optional) Add a `brands/controlel/` folder with a brand icon and manifest.

**Who should fix:** Qwen can safely add a brands folder if desired.

---

## Summary Table

| # | Area | Status | Notes |
|---|------|--------|-------|
| 1 | HACS manifest | PASS | Correct and complete |
| 2 | HA manifest | PASS | Correct, pinned to controlel==0.12.0 |
| 3 | Localization | PASS | Complete, truthful, en only |
| 4 | Config flow | PASS | Comprehensive, validated |
| 5 | Diagnostics | PASS | Privacy-minimized, comprehensive |
| 6 | Lifecycle | PASS | Robust, non-fatal panel failure |
| 7 | Panel | PASS | Idempotent, read-only, safe |
| 8 | Frontend | PASS | 77 tests pass, truthful, i18n |
| 9 | HACS build/validator | PASS | Deterministic, comprehensive |
| 10 | Integration tests | PASS | Thorough, real HA loader |
| 11 | CI workflows | PASS | Complete, validation-only |
| 12 | Core 0.12 composition | **BLOCKED** | Pending Core 0.13 publication |
| 13 | Release docs | **FAIL** | Stale (describes 0.12.0 without frontend) |
| 14 | HACS branding | PASS | Optional, HACS ignores missing brands |

---

## Recommendations

1. **Resolve the Core 0.13 dependency** (BLOCKED): Publish Core 0.13.0 with Frontend API v1, then update the integration manifest to pin `controlel==0.13.0`. This is a prerequisite for HACS publication.

2. **Fix the release documentation inconsistency** (FAIL): Update `docs/releases/home-assistant-0.12.0.md`, `release-metadata/releases.yaml`, and `docs/development/ReleaseGuide.md` to accurately describe the 0.12.0 scope (including the frontend panel and Frontend API v1 transport), or bump the version to 0.13.0.

3. **(Optional) Add HACS branding:** Create a `brands/controlel/` folder with a brand icon and manifest for a better UI experience.

---

## Appendix: Verification Commands

```bash
# Frontend behavior tests
cd custom_components/controlel/frontend
node --test tests/app.test.js tests/api-client.test.js tests/i18n.test.js
# Result: 77 passed, 0 failed

# HACS build
python scripts/packaging/build_hacs_release.py --version 0.12.0
# Result: success, SHA-256 30758555307cbc5668cb350bf8e5c0eb1c9d6e321f9001a8a33461d600c6de76

# HACS validation
python scripts/packaging/validate_hacs_release.py dist/hacs/controlel.zip --version 0.12.0
# Result: success

# Archive inspection
python -c "import zipfile; z=zipfile.ZipFile('dist/hacs/controlel.zip'); print(len(z.namelist()), 'files')"
# Result: 37 files
```

---

*Audit completed by Qwen (LM Studio Bionic). Read-only review, no production code modified.*
