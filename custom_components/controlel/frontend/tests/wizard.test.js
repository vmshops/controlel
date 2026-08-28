/* Controlel canonical-v3 setup wizard boundary tests (Node, no dependencies). */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { Element, documentStub } = require("./dom-stub");

global.document = documentStub;
global.window = globalThis;
require("../i18n.js");
require("../components.js");
require("../wizard.js");
globalThis.CI18N.setLanguage("en");

const W = globalThis.CA_WIZARD;
const NOW = "2026-08-24T12:00:00Z";
const IDS = { sensor: "a".repeat(64), enable: "b".repeat(64), disable: "c".repeat(64) };

function roots() {
  const root = new Element("div");
  const draftStatus = new Element("div"); draftStatus.id = "draft-status";
  const stepper = new Element("nav"); stepper.id = "stepper";
  const panel = new Element("section"); panel.id = "step-panel";
  const footer = new Element("footer"); footer.id = "wizard-footer";
  root.append(draftStatus, stepper, panel, footer);
  documentStub._root = root;
  return { root, draftStatus, stepper, panel, footer };
}

function object(objectKind, nativeId, currentLocator, areaId = null, overrides = {}) {
  return {
    object_kind: objectKind, native_id: nativeId, current_locator: currentLocator,
    identity_quality: "STABLE", device_registry_id: null, area_id: areaId, floor_id: null, ...overrides,
  };
}

function snapshot(overrides = {}) {
  return {
    snapshot_id: "snapshot-real", provider: "home_assistant", provider_instance_id: "ha-real-instance",
    captured_at: NOW, content_fingerprint: "f".repeat(64),
    object_counts: { "home_assistant.area": 1, "home_assistant.entity": 2 },
    objects: [
      object("home_assistant.area", "living", null),
      object("home_assistant.entity", "sensor-registry-id", "sensor.living_temperature", "living"),
      object("home_assistant.entity", "switch-registry-id", "switch.boiler", "living"),
    ],
    ...overrides,
  };
}

function candidate(id, role, nativeId, locator, domain, overrides = {}) {
  const base = {
    candidate_id: id, role, native_id: nativeId, current_locator: locator, identity_quality: "STABLE",
    area_id: "living", floor_id: null,
    capabilities: [domain === "sensor" ? "measurement.temperature" : "command.enable_disable"],
    confidence: "HIGH", reason_codes: [`heating.candidate.${domain}`], evidence: { domain, area_id: "living" },
  };
  return { ...base, ...overrides, evidence: { ...base.evidence, ...(overrides.evidence || {}) } };
}

function recommendations(overrides = {}) {
  const values = {
    sensor: candidate(IDS.sensor, W.PRIMARY_TEMPERATURE_ROLE, "sensor-registry-id", "sensor.living_temperature", "sensor"),
    enable: candidate(IDS.enable, W.SOURCE_ENABLE_TARGET_ROLE, "switch-registry-id", "switch.boiler", "switch"),
    disable: candidate(IDS.disable, W.SOURCE_DISABLE_TARGET_ROLE, "switch-registry-id", "switch.boiler", "switch"),
    ...overrides,
  };
  return [
    [W.PRIMARY_TEMPERATURE_ROLE, values.sensor],
    [W.SOURCE_ENABLE_TARGET_ROLE, values.enable],
    [W.SOURCE_DISABLE_TARGET_ROLE, values.disable],
  ].map(([role, recommended]) => ({ role, recommended, alternatives: [], explicit_confirmation_required: true }));
}

function defaults() {
  return {
    core_version: "0.15.0", integration_version: "0.13.0",
    settings: {
      target_temperature_celsius: 21, primary_measurement_max_age_seconds: 900,
      maximum_future_skew_seconds: 30, indeterminate_grace_period_seconds: 120,
      heating_turn_on_differential_celsius: 0.3, heating_turn_off_differential_celsius: 0.1,
      heat_demand_confirmation_seconds: 120, minimum_heating_on_seconds: 600,
      minimum_heating_off_seconds: 300,
    },
    simple_switch: {},
  };
}

function reference(nativeId, locator, objectKind = "home_assistant.entity") {
  return {
    provider: "home_assistant", provider_instance_id: "ha-real-instance", object_kind: objectKind,
    native_id: nativeId, identity_quality: "STABLE", current_locator: locator, device_registry_id: null,
    area_id: objectKind === "home_assistant.entity" ? "living" : null, floor_id: null, recovery_evidence: {},
  };
}

function canonicalDraft({ revision = 1, draftId = "draft-real", scopes = null, sensorReference = null } = {}) {
  const area = reference("living", null, "home_assistant.area");
  const sensor = sensorReference || reference("sensor-registry-id", "sensor.living_temperature");
  const source = reference("switch-registry-id", "switch.boiler");
  const document = scopes || {
    heating: {
      global: { maximum_future_skew_seconds: 30 },
      zones: [{
        zone_id: "main_zone", display_name: "Living room",
        topology: { area_reference: area, floor_reference: null },
        primary_temperature_sensor: {
          sensor_id: "primary_temperature_sensor", display_name: "Living temperature", provider_reference: sensor,
        },
        demand_policy: {
          target_temperature_celsius: 21, heating_turn_on_differential_celsius: 0.3,
          heating_turn_off_differential_celsius: 0.1, heat_demand_confirmation_seconds: 120,
          primary_measurement_max_age_seconds: 900,
        },
      }],
      heat_sources: [{
        heat_source_id: "main_heat_source", display_name: "Boiler permission", provider_reference: source,
        command_strategy: {
          mode: "simple",
          enable_permission: { domain: "switch", service: "turn_on", command_target_reference: source },
          disable_permission: { domain: "switch", service: "turn_off", command_target_reference: source },
        },
        observations: { reported_actuator_state_reference: source, physical_operation_reference: null },
        protection: {
          indeterminate_grace_period_seconds: 120, indeterminate_timeout_action: "disable_heating",
          minimum_heating_on_seconds: 600, minimum_heating_off_seconds: 300,
        },
      }],
      heat_delivery: [{
        zone_id: "main_zone", mode: "unmanaged", actuator_reference: null, ownership: "device_owned",
        assist_policy: "no_assist", assist_target_celsius: 30,
      }],
    },
    diagnostics: { steady_profile: "detailed", debug_policy: { configured_duration_seconds: 1234, until_changed: true } },
    notifications: {
      enabled: false, recipients: [], maximum_per_window: 7, rate_window_seconds: 60,
      critical_maximum_per_window: 3, critical_rate_window_seconds: 60, history_capacity: 99,
    },
  };
  return {
    schema_version: 3, draft_id: draftId, revision, configuration_id: "heating-config",
    base_active_revision_id: null, base_active_generation: 0, canonical_revision: 1, parent_revision_id: null,
    environment_id: "ha-real-instance", provider: "home_assistant", provider_instance_id: "ha-real-instance",
    created_at: NOW, updated_at: NOW, lineage: { authoring_origin: "greenfield_v3" },
    import_provenance: {}, migration_provenance: {}, ...document,
  };
}

function draftFromBindings(request) {
  const bindings = request.bindings;
  const draft = canonicalDraft({ draftId: request.draft_id });
  draft.heating.zones[0].display_name = bindings.zone_display_name;
  draft.heating.zones[0].topology = bindings.topology;
  draft.heating.zones[0].primary_temperature_sensor.display_name = bindings.primary_sensor_display_name;
  draft.heating.zones[0].primary_temperature_sensor.provider_reference = bindings.primary_temperature_sensor_reference;
  draft.heating.heat_sources[0].display_name = bindings.heat_source_display_name;
  draft.heating.heat_sources[0].provider_reference = bindings.heat_source_reference;
  draft.heating.heat_sources[0].command_strategy = bindings.command_strategy;
  draft.heating.heat_sources[0].observations = bindings.observations;
  return draft;
}

function apiError(code, message = code) { const error = new Error(message); error.code = code; return error; }

function fakeClient({ drafts = [], reopen = null, active = null, validationReady = true, failures = {} } = {}) {
  const calls = [];
  return {
    calls,
    discover(request) { calls.push(["discovery", request]); return failures.discovery ? Promise.reject(failures.discovery) : Promise.resolve(snapshot()); },
    recommendations(request) { calls.push(["recommendations", request]); return Promise.resolve(recommendations()); },
    defaults() { calls.push(["defaults", {}]); return Promise.resolve(defaults()); },
    listDrafts() { calls.push(["drafts", {}]); return Promise.resolve(drafts); },
    reopenDraft(request) {
      calls.push(["draft", request]);
      const reopenFailure = typeof failures.reopen === "function" ? failures.reopen(request) : failures.reopen;
      if (reopenFailure) return Promise.reject(reopenFailure);
      return Promise.resolve(reopen || drafts.find((item) => item.draft_id === request.draft_id) || canonicalDraft({ draftId: request.draft_id }));
    },
    readActive(request) {
      calls.push(["active", request]);
      return active ? Promise.resolve(active) : Promise.reject(apiError("setup_conflict", "no active canonical configuration"));
    },
    editDraft(request) {
      calls.push(["edit", request]);
      const draft = canonicalDraft({ draftId: request.draft_id });
      draft.base_active_revision_id = active.active_reference.canonical_revision_id;
      draft.base_active_generation = active.active_reference.generation;
      return Promise.resolve(draft);
    },
    startDraft(request) { calls.push(["start", request]); return Promise.resolve(draftFromBindings(request)); },
    updateDraft(request) {
      calls.push(["update", request]);
      if (failures.update) return Promise.reject(failures.update);
      return Promise.resolve(canonicalDraft({ revision: request.expected_revision + 1, draftId: request.draft_id, scopes: request.configuration_scopes }));
    },
    validateDraft(request) {
      calls.push(["validate", request]);
      if (failures.validate) return Promise.reject(failures.validate);
      return Promise.resolve({
        report_id: request.report_id, draft_id: request.draft_id, draft_revision: 2,
        draft_fingerprint: "d".repeat(64), evaluated_at: NOW, reference_health: [],
        activation_ready: validationReady,
        issue_codes: validationReady ? [] : ["canonical_v3.reference.missing"],
      });
    },
    canonicalizeDraft(request) {
      calls.push(["canonicalize", request]);
      return Promise.resolve({ ...canonicalDraft(), revision_id: request.revision_id, semantic_configuration_fingerprint: "e".repeat(64) });
    },
    activateRevision(request) {
      calls.push(["activate", request]);
      return Promise.resolve({ generation: 1, canonical_revision_id: request.revision_id });
    },
    abandonDraft(request) {
      calls.push(["abandon", request]);
      return Promise.resolve({ draft_id: request.draft_id, abandoned_revision: request.expected_revision });
    },
  };
}

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, value); }, removeItem(key) { values.delete(key); }, values,
  };
}

function create(client, storage = memoryStorage(), overrides = {}) {
  const dom = roots();
  let sequence = 0;
  const wizard = W.createSetupWizard({
    client, root: dom.root, configEntryId: "entry-real", storage, now: () => NOW,
    idFactory: (prefix) => `${prefix}-${++sequence}`, ...overrides,
  });
  return { ...dom, wizard, storage };
}

function selectCompleteIntent(wizard) {
  wizard.state.draft.areaId = "living";
  wizard.state.draft.areaTouched = true;
  wizard.state.draft.selections = {
    [W.PRIMARY_TEMPERATURE_ROLE]: IDS.sensor,
    [W.SOURCE_ENABLE_TARGET_ROLE]: IDS.enable,
    [W.SOURCE_DISABLE_TARGET_ROLE]: IDS.disable,
  };
  wizard.state.draft.confirmations = {
    [W.PRIMARY_TEMPERATURE_ROLE]: true,
    [W.SOURCE_ENABLE_TARGET_ROLE]: true,
    [W.SOURCE_DISABLE_TARGET_ROLE]: true,
  };
  wizard.state.draft.touchedRoles = {
    [W.PRIMARY_TEMPERATURE_ROLE]: true,
    [W.SOURCE_ENABLE_TARGET_ROLE]: true,
    [W.SOURCE_DISABLE_TARGET_ROLE]: true,
  };
  wizard.state.dirty = true;
}

function advanceToStep(wizard, target) {
  while (wizard.state.step < target) {
    assert.equal(wizard.advanceStep(), true);
  }
}

function stepperStepNodes(stepperNav, stepNumber) {
  return [...stepperNav.walk()].filter((node) =>
    node.className && node.className.includes("stepper__step") &&
    [...node.walk()].some((child) =>
      child.className === "stepper__index" && child.textContent === String(stepNumber)
    )
  );
}

test("greenfield discovery is read-only until required bindings are explicitly saved", async () => {
  const client = fakeClient();
  const { footer, panel, wizard, storage } = create(client);
  await wizard.startDiscovery();

  assert.equal(wizard.state.status, "loaded");
  assert.equal(wizard.state.session, null);
  assert.deepEqual(client.calls.map(([operation]) => operation), ["discovery", "recommendations", "defaults", "drafts", "active"]);
  assert.equal(client.calls.some(([operation]) => ["start", "update", "validate", "canonicalize", "activate"].includes(operation)), false);
  assert.equal(storage.values.size, 0);
  assert.ok(panel.textContent.includes("ha-real-instance"));
  assert.ok(footer.findButton("Continue"));
});

test("Save Draft creates and updates only canonical v3 state", async () => {
  const client = fakeClient();
  const { wizard, storage } = create(client);
  await wizard.startDiscovery();
  selectCompleteIntent(wizard);
  await wizard.saveDraft();

  assert.deepEqual(client.calls.slice(-2).map(([operation]) => operation), ["start", "update"]);
  assert.equal(wizard.state.session.schema_version, 3);
  assert.equal(wizard.state.session.revision, 2);
  assert.equal(storage.values.get("controlel.configuration.draft.v3.entry-real"), wizard.state.session.draft_id);
  const start = client.calls.find(([operation]) => operation === "start")[1];
  assert.equal(start.bindings.command_strategy.mode, "simple");
  assert.equal(start.bindings.command_strategy.enable_permission.service, "turn_on");
  assert.equal(start.bindings.command_strategy.disable_permission.service, "turn_off");
  assert.equal(start.bindings.observations.physical_operation_reference, null);
});

test("Validate, Canonicalize, and Activate are distinct explicit operations", async () => {
  const client = fakeClient({ drafts: [canonicalDraft({ revision: 2 })] });
  const { wizard } = create(client);
  await wizard.startDiscovery();
  await wizard.validateDraft();
  assert.equal(wizard.state.validation.activation_ready, true);
  assert.equal(client.calls.some(([operation]) => operation === "canonicalize" || operation === "activate"), false);

  await wizard.canonicalizeDraft();
  assert.ok(wizard.state.candidateRevision);
  assert.equal(client.calls.some(([operation]) => operation === "activate"), false);
  await wizard.activateRevision();
  assert.ok(wizard.state.activation);
  assert.deepEqual(client.calls.slice(-3).map(([operation]) => operation), ["validate", "canonicalize", "activate"]);
});

test("Wizard resumes a canonical draft created by HA Configure without a browser pointer", async () => {
  const client = fakeClient({ drafts: [canonicalDraft({ draftId: "ha-configure-draft", revision: 4 })] });
  const { wizard, storage } = create(client);
  await wizard.startDiscovery();

  assert.equal(wizard.state.session.draft_id, "ha-configure-draft");
  assert.equal(wizard.state.step, 1);
  assert.equal(storage.values.get("controlel.configuration.draft.v3.entry-real"), "ha-configure-draft");
});

test("invalid resumed references stay on step 1 with prefilled session data", async () => {
  const missing = reference("missing-sensor", "sensor.removed");
  const client = fakeClient({ drafts: [canonicalDraft({ sensorReference: missing })] });
  const { wizard } = create(client);
  await wizard.startDiscovery();

  assert.equal(wizard.state.step, 1);
  assert.equal(wizard.state.draft.selections[W.PRIMARY_TEMPERATURE_ROLE], undefined);
});

test("a stale local pointer is cleared without creating a legacy draft", async () => {
  const storage = memoryStorage({ "controlel.configuration.draft.v3.entry-real": "stale-draft" });
  const client = fakeClient({ failures: { reopen: apiError("not_found") } });
  const { wizard } = create(client, storage);
  await wizard.startDiscovery();

  assert.equal(wizard.state.status, "loaded");
  assert.equal(wizard.state.session, null);
  assert.equal(storage.values.has("controlel.configuration.draft.v3.entry-real"), false);
  assert.equal(client.calls.some(([operation]) => operation === "start"), false);
});

test("a stale local pointer falls back to the newest canonical backend draft", async () => {
  const storage = memoryStorage({ "controlel.configuration.draft.v3.entry-real": "stale-draft" });
  const backendDraft = canonicalDraft({ draftId: "ha-configure-draft", revision: 6 });
  const client = fakeClient({
    drafts: [backendDraft],
    failures: { reopen: (request) => request.draft_id === "stale-draft" ? apiError("not_found") : null },
  });
  const { wizard } = create(client, storage);
  await wizard.startDiscovery();

  assert.deepEqual(
    client.calls.filter(([operation]) => operation === "draft").map(([, request]) => request.draft_id),
    ["stale-draft", "ha-configure-draft"]
  );
  assert.equal(wizard.state.session.draft_id, "ha-configure-draft");
  assert.equal(storage.values.get("controlel.configuration.draft.v3.entry-real"), "ha-configure-draft");
});

test("active canonical v3 authority is cloned and remains unchanged until activation", async () => {
  const active = {
    active_reference: { canonical_revision_id: "active-v3", generation: 7 },
    canonical_revision: { schema_version: 3, revision_id: "active-v3" }, configuration_scopes: {},
  };
  const client = fakeClient({ active });
  const { wizard } = create(client);
  await wizard.startDiscovery();

  assert.deepEqual(client.calls.slice(-2).map(([operation]) => operation), ["active", "edit"]);
  assert.equal(wizard.state.session.base_active_revision_id, "active-v3");
  assert.equal(wizard.state.session.base_active_generation, 7);
  assert.equal(client.calls.some(([operation]) => operation === "activate"), false);
});

test("editing Wizard fields preserves canonical scopes outside its compact surface", async () => {
  const shared = canonicalDraft({ revision: 3 });
  const client = fakeClient({ drafts: [shared] });
  const { wizard } = create(client);
  await wizard.startDiscovery();
  wizard.state.draft.settings.target_temperature_celsius = 22.5;
  wizard.state.dirty = true;
  await wizard.saveDraft();

  const scopes = client.calls.find(([operation]) => operation === "update")[1].configuration_scopes;
  assert.equal(scopes.heating.zones[0].demand_policy.target_temperature_celsius, 22.5);
  assert.deepEqual(scopes.diagnostics, shared.diagnostics);
  assert.deepEqual(scopes.notifications, shared.notifications);
  assert.deepEqual(scopes.heating.heat_delivery, shared.heating.heat_delivery);
  assert.deepEqual(scopes.heating.heat_sources[0].command_strategy, shared.heating.heat_sources[0].command_strategy);
});

test("blocking validation stays Not Ready and cannot canonicalize", async () => {
  const client = fakeClient({ drafts: [canonicalDraft({ revision: 2 })], validationReady: false });
  const { panel, wizard } = create(client);
  await wizard.startDiscovery();
  advanceToStep(wizard, 5);
  await wizard.validateDraft();

  assert.ok(panel.textContent.includes("Not Ready"));
  assert.ok(panel.textContent.includes("canonical_v3.reference.missing"));
  assert.equal(await wizard.canonicalizeDraft(), null);
  assert.equal(client.calls.some(([operation]) => operation === "canonicalize"), false);
});

test("abandon is confirmed and uses the canonical-v3 draft revision", async () => {
  const client = fakeClient({ drafts: [canonicalDraft({ revision: 6 })] });
  const { wizard } = create(client, memoryStorage(), { confirm: () => true });
  await wizard.startDiscovery();
  await wizard.deleteDraft();

  assert.deepEqual(client.calls.find(([operation]) => operation === "abandon")[1], {
    draft_id: "draft-real", expected_revision: 6,
  });
});

test("candidate filtering preserves capability checks and excludes self and unstable identities", () => {
  const sensor = candidate(IDS.sensor, W.PRIMARY_TEMPERATURE_ROLE, "sensor-registry-id", "sensor.room", "sensor");
  assert.equal(W.isWizardCandidateCompatible(W.PRIMARY_TEMPERATURE_ROLE, sensor), true);
  assert.equal(W.isWizardCandidateCompatible(W.SOURCE_ENABLE_TARGET_ROLE, sensor), false);
  assert.equal(W.isWizardCandidateCompatible(W.PRIMARY_TEMPERATURE_ROLE, { ...sensor, identity_quality: "EPHEMERAL", native_id: null }), false);
  assert.equal(W.isWizardCandidateCompatible(W.PRIMARY_TEMPERATURE_ROLE, {
    ...sensor, current_locator: "sensor.controlel_room", evidence: { domain: "sensor", platform: "controlel" },
  }), false);
});

test("one switch selection pairs enable and disable while confirmation remains explicit", async () => {
  const client = fakeClient();
  const { panel, wizard } = create(client);
  await wizard.startDiscovery();
  advanceToStep(wizard, 3);
  const switchRadio = panel.walk().find((node) =>
    node.tagName === "INPUT" && node.getAttribute("type") === "radio" && node.getAttribute("name") === IDS.enable
  );
  switchRadio.dispatch("change");

  assert.equal(wizard.state.draft.selections[W.SOURCE_ENABLE_TARGET_ROLE], IDS.enable);
  assert.equal(wizard.state.draft.selections[W.SOURCE_DISABLE_TARGET_ROLE], IDS.disable);
  assert.equal(wizard.state.draft.confirmations[W.SOURCE_ENABLE_TARGET_ROLE], false);
  assert.equal(wizard.state.draft.confirmations[W.SOURCE_DISABLE_TARGET_ROLE], false);
});

test("backend failures stay explicit with no mock fallback", async () => {
  const discovery = create(fakeClient({ failures: { discovery: new Error("registry unavailable") } }));
  await discovery.wizard.startDiscovery();
  assert.equal(discovery.wizard.state.status, "error");
  assert.ok(discovery.panel.textContent.includes("registry unavailable"));

  const validation = create(fakeClient({
    drafts: [canonicalDraft({ revision: 2 })], failures: { validate: new Error("validation unavailable") },
  }));
  await validation.wizard.startDiscovery();
  advanceToStep(validation.wizard, 5);
  await validation.wizard.validateDraft();
  assert.equal(validation.wizard.state.status, "error");
  assert.ok(validation.panel.textContent.includes("validation unavailable"));
});

function haosSnapshot() {
  return snapshot({
    snapshot_id: "snapshot-haos",
    objects: [
      object("home_assistant.area", "tiskacka", null),
      object("home_assistant.entity", "synology-teplota-registry", "sensor.synology_teplota", "tiskacka"),
      object("home_assistant.entity", "smart-wifi-plug-registry", "switch.smart_wi_fi_plug", "tiskacka"),
    ],
    object_counts: { "home_assistant.area": 1, "home_assistant.entity": 2 },
  });
}

function haosRecommendations() {
  const sensor = candidate(
    IDS.sensor, W.PRIMARY_TEMPERATURE_ROLE, "synology-teplota-registry", "sensor.synology_teplota", "sensor"
  );
  const source = candidate(
    IDS.enable, W.SOURCE_ENABLE_TARGET_ROLE, "smart-wifi-plug-registry", "switch.smart_wi_fi_plug", "switch"
  );
  const disable = candidate(
    IDS.disable, W.SOURCE_DISABLE_TARGET_ROLE, "smart-wifi-plug-registry", "switch.smart_wi_fi_plug", "switch"
  );
  return [
    { role: W.PRIMARY_TEMPERATURE_ROLE, recommended: sensor, alternatives: [], explicit_confirmation_required: true },
    { role: W.SOURCE_ENABLE_TARGET_ROLE, recommended: source, alternatives: [], explicit_confirmation_required: true },
    { role: W.SOURCE_DISABLE_TARGET_ROLE, recommended: disable, alternatives: [], explicit_confirmation_required: true },
  ];
}

function haosClient(overrides = {}) {
  const calls = [];
  const client = {
    calls,
    discover() { calls.push(["discovery", {}]); return Promise.resolve(haosSnapshot()); },
    recommendations() { calls.push(["recommendations", {}]); return Promise.resolve(haosRecommendations()); },
    defaults() { calls.push(["defaults", {}]); return Promise.resolve(defaults()); },
    listDrafts() { calls.push(["drafts", {}]); return Promise.resolve([]); },
    reopenDraft(request) { calls.push(["draft", request]); return Promise.reject(apiError("not_found")); },
    readActive() { return Promise.reject(apiError("setup_conflict")); },
    editDraft() { return Promise.reject(apiError("setup_conflict")); },
    startDraft(request) { calls.push(["start", request]); return Promise.resolve(draftFromBindings(request)); },
    updateDraft(request) {
      calls.push(["update", request]);
      return Promise.resolve(canonicalDraft({
        revision: request.expected_revision + 1,
        draftId: request.draft_id,
        scopes: request.configuration_scopes,
      }));
    },
    validateDraft(request) {
      calls.push(["validate", request]);
      const update = calls.find(([operation]) => operation === "update");
      const revision = update ? update[1].expected_revision + 1 : 1;
      return Promise.resolve({
        report_id: request.report_id,
        draft_id: request.draft_id,
        draft_revision: revision,
        draft_fingerprint: "d".repeat(64),
        evaluated_at: NOW,
        reference_health: [],
        activation_ready: true,
        issue_codes: [],
      });
    },
    canonicalizeDraft(request) {
      calls.push(["canonicalize", request]);
      return Promise.resolve({ ...canonicalDraft(), revision_id: request.revision_id, semantic_configuration_fingerprint: "e".repeat(64) });
    },
    activateRevision(request) {
      calls.push(["activate", request]);
      return Promise.resolve({ generation: 1, canonical_revision_id: request.revision_id });
    },
    abandonDraft(request) {
      calls.push(["abandon", request]);
      return Promise.resolve({ draft_id: request.draft_id, abandoned_revision: request.expected_revision });
    },
    ...overrides,
  };
  return client;
}

function selectHaosIntent(wizard) {
  wizard.state.draft.areaId = "tiskacka";
  wizard.state.draft.areaTouched = true;
  wizard.state.draft.selections = {
    [W.PRIMARY_TEMPERATURE_ROLE]: IDS.sensor,
    [W.SOURCE_ENABLE_TARGET_ROLE]: IDS.enable,
    [W.SOURCE_DISABLE_TARGET_ROLE]: IDS.disable,
  };
  wizard.state.draft.confirmations = {
    [W.PRIMARY_TEMPERATURE_ROLE]: true,
    [W.SOURCE_ENABLE_TARGET_ROLE]: true,
    [W.SOURCE_DISABLE_TARGET_ROLE]: true,
  };
  wizard.state.draft.settings.target_temperature_celsius = 21;
  wizard.state.dirty = true;
}

test("HAOS greenfield validate persists confirmed bindings before validation", async () => {
  const client = haosClient();
  const { wizard } = create(client);
  await wizard.startDiscovery();
  selectHaosIntent(wizard);
  advanceToStep(wizard, 5);
  await wizard.validateDraft();

  assert.equal(wizard.state.dirty, false);
  assert.equal(wizard.state.validation.draft_revision, wizard.state.session.revision);
  assert.equal(wizard.state.validation.activation_ready, true);
  assert.deepEqual(client.calls.slice(-3).map(([operation]) => operation), ["start", "update", "validate"]);
  const update = client.calls.find(([operation]) => operation === "update")[1];
  const sensor = update.configuration_scopes.heating.zones[0].primary_temperature_sensor.provider_reference;
  const enable = update.configuration_scopes.heating.heat_sources[0].command_strategy.enable_permission.command_target_reference;
  assert.equal(sensor.current_locator, "sensor.synology_teplota");
  assert.equal(enable.current_locator, "switch.smart_wi_fi_plug");
  assert.equal(update.configuration_scopes.heating.zones[0].demand_policy.target_temperature_celsius, 21);
});

test("confirmed bindings persist when touchedRoles were cleared before update", async () => {
  const staleSensor = reference("stale-sensor-registry", "sensor.stale_temperature");
  const staleDraft = canonicalDraft({ revision: 3, sensorReference: staleSensor });
  const client = fakeClient({ drafts: [staleDraft] });
  const { wizard } = create(client);
  await wizard.startDiscovery();

  wizard.state.draft.selections[W.PRIMARY_TEMPERATURE_ROLE] = IDS.sensor;
  wizard.state.draft.confirmations[W.PRIMARY_TEMPERATURE_ROLE] = true;
  wizard.state.draft.touchedRoles = {};
  wizard.state.dirty = true;
  await wizard.saveDraft();

  const update = client.calls.find(([operation]) => operation === "update")[1];
  const sensor = update.configuration_scopes.heating.zones[0].primary_temperature_sensor.provider_reference;
  assert.equal(sensor.current_locator, "sensor.living_temperature");
  assert.equal(wizard.state.dirty, false);
});

test("discovery keeps step 1 and explicit Next advances one step at a time", async () => {
  const client = fakeClient();
  const { wizard } = create(client);
  await wizard.startDiscovery();

  assert.equal(wizard.state.step, 1);
  assert.equal(wizard.state.session, null);
  assert.equal(wizard.state.draft.selections[W.PRIMARY_TEMPERATURE_ROLE], IDS.sensor);
  assert.equal(wizard.state.draft.confirmations[W.PRIMARY_TEMPERATURE_ROLE], undefined);

  assert.equal(wizard.advanceStep(), true);
  assert.equal(wizard.state.step, 2);
  assert.equal(wizard.advanceStep(), true);
  assert.equal(wizard.state.step, 3);
  assert.equal(wizard.advanceStep(), true);
  assert.equal(wizard.state.step, 4);
  assert.equal(wizard.advanceStep(), true);
  assert.equal(wizard.state.step, 5);
  assert.equal(wizard.advanceStep(), false);
});

test("delete draft resets navigation to step 1 without restoring review position", async () => {
  const client = fakeClient({ drafts: [canonicalDraft({ revision: 6 })] });
  const { wizard } = create(client, memoryStorage(), { confirm: () => true });
  await wizard.startDiscovery();
  advanceToStep(wizard, 5);
  await wizard.deleteDraft();

  assert.equal(wizard.state.step, 1);
  assert.equal(wizard.state.session, null);
  assert.equal(wizard.state.validation, null);
});

test("resumed complete draft stays on step 1 until explicit navigation", async () => {
  const client = fakeClient({ drafts: [canonicalDraft({ revision: 4 })] });
  const { wizard } = create(client);
  await wizard.startDiscovery();

  assert.equal(wizard.state.step, 1);
  assert.equal(wizard.state.draft.confirmations[W.PRIMARY_TEMPERATURE_ROLE], true);
  for (let expected = 2; expected <= 5; expected += 1) {
    assert.equal(wizard.advanceStep(), true);
    assert.equal(wizard.state.step, expected);
  }
});

test("validation correction navigates only after an explicit fix action", async () => {
  const missing = reference("missing-sensor", "sensor.removed");
  const client = fakeClient({ drafts: [canonicalDraft({ sensorReference: missing })], validationReady: false });
  const { panel, wizard } = create(client);
  await wizard.startDiscovery();
  assert.equal(wizard.state.step, 1);
  advanceToStep(wizard, 5);
  await wizard.validateDraft();

  assert.equal(wizard.state.step, 5);
  assert.ok(panel.textContent.includes("canonical_v3.reference.missing"));

  wizard.goToCorrectionStep();
  assert.equal(wizard.state.step, 3);
});

test("stepper clicks cannot jump forward from step 1", async () => {
  const client = fakeClient();
  const { stepper, wizard } = create(client);
  await wizard.startDiscovery();
  assert.equal(wizard.state.step, 1);

  for (const stepNumber of [4, 5]) {
    const nodes = stepperStepNodes(stepper, stepNumber);
    assert.equal(nodes.length, 1);
    assert.equal(nodes[0].listeners.click, undefined);
    nodes[0].dispatch("click");
    assert.equal(wizard.state.step, 1, `stepper step ${stepNumber} must not advance the wizard`);
  }

  assert.equal(wizard.advanceStep(), true);
  assert.equal(wizard.state.step, 2);
  assert.equal(wizard.retreatStep(), true);
  assert.equal(wizard.state.step, 1);
});
