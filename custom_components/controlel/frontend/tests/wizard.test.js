/* Controlel real setup wizard boundary tests (Node, no dependencies). */
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
const IDS = {
  sensor: "a".repeat(64),
  enable: "b".repeat(64),
  disable: "c".repeat(64),
};

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

function snapshot() {
  return {
    snapshot_id: "snapshot-real",
    provider: "home_assistant",
    provider_instance_id: "ha-real-instance",
    captured_at: "2026-08-24T12:00:00Z",
    content_fingerprint: "f".repeat(64),
    object_counts: {
      "home_assistant.area": 1,
      "home_assistant.entity": 2,
    },
    objects: [{
      object_kind: "home_assistant.area",
      native_id: "living",
      current_locator: null,
      identity_quality: "STABLE",
      device_registry_id: null,
      area_id: null,
      floor_id: null,
    }],
  };
}

function candidate(id, role, locator, domain) {
  return {
    candidate_id: id,
    role,
    native_id: `${domain}-registry-id`,
    current_locator: locator,
    identity_quality: "STABLE",
    area_id: "living",
    floor_id: null,
    capabilities: [domain === "sensor" ? "measurement.temperature" : "command.enable_disable"],
    confidence: "HIGH",
    reason_codes: [`heating.candidate.${domain}`],
    evidence: { domain, area_id: "living" },
  };
}

function recommendations() {
  return [
    [W.PRIMARY_TEMPERATURE_ROLE, IDS.sensor, "sensor.living_temperature", "sensor"],
    [W.SOURCE_ENABLE_TARGET_ROLE, IDS.enable, "switch.boiler", "switch"],
    [W.SOURCE_DISABLE_TARGET_ROLE, IDS.disable, "switch.boiler", "switch"],
  ].map(([role, id, locator, domain]) => ({
    role,
    recommended: candidate(id, role, locator, domain),
    alternatives: [],
    explicit_confirmation_required: true,
  }));
}

function session(overrides = {}) {
  return Object.assign({
    draft_id: "draft-real",
    draft_revision: 1,
    module_instance_id: "main-heating",
    incomplete: true,
    activation_ready: false,
    validation_status: "CURRENT",
    validation_report_id: "report-real",
    blocking_issue_count: 3,
    warning_count: 0,
    settings: {},
    selections: [],
    recommendations: recommendations(),
    validation_issues: [{
      code: "heating.invalid_setting",
      severity: "ERROR",
      path: ["target_temperature_celsius"],
      module_role: null,
      message_key: "setup.heating.invalid_setting",
      parameters: { error_type: "missing" },
      evidence: {},
      suggested_action: null,
    }],
    discovery: snapshot(),
    canonical_revision_id: null,
    active_revision_id: null,
    legacy_configuration: { present: false, conversion_available: false, silently_merged: false, reason_code: null },
  }, overrides);
}

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, value); },
    removeItem(key) { values.delete(key); },
    values,
  };
}

function fakeClient({
  failDiscovery = false,
  failUpdate = false,
  reopenOverrides = {},
  updateOverrides = {},
} = {}) {
  const calls = [];
  return {
    calls,
    discover(request) {
      calls.push(["discovery", request]);
      return failDiscovery ? Promise.reject(new Error("registry unavailable")) : Promise.resolve(snapshot());
    },
    recommendations(request) {
      calls.push(["recommendations", request]);
      return Promise.resolve(recommendations());
    },
    startDraft(request) {
      calls.push(["start", request]);
      return Promise.resolve(session({ draft_id: request.draft_id }));
    },
    reopenDraft(request) {
      calls.push(["reopen", request]);
      return Promise.resolve(session({ draft_id: request.draft_id, ...reopenOverrides }));
    },
    updateDraft(request) {
      calls.push(["update", request]);
      if (failUpdate) return Promise.reject(new Error("draft validation failed"));
      const selections = request.selections.map((item) => ({
        ...item,
        native_id: "registry-id",
        current_locator: candidate(item.candidate_id, item.role, "entity.real", "switch").current_locator,
        identity_quality: "STABLE",
        selection_origin: "RECOMMENDATION_ACCEPTED",
        resolution_status: "RESOLVED",
      }));
      return Promise.resolve(session({
        draft_revision: request.expected_revision + 1,
        settings: request.settings,
        selections,
        ...updateOverrides,
      }));
    },
    validateDraft(request) {
      calls.push(["validate", request]);
      return Promise.resolve(session({ draft_revision: 2 }));
    },
  };
}

function create(client, storage = memoryStorage()) {
  const dom = roots();
  let sequence = 0;
  const wizard = W.createSetupWizard({
    client,
    root: dom.root,
    configEntryId: "entry-real",
    storage,
    now: () => "2026-08-24T12:00:00Z",
    idFactory: (prefix) => `${prefix}-${++sequence}`,
  });
  return { ...dom, wizard, storage };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test("wizard starts real discovery and creates a persisted backend draft", async () => {
  const client = fakeClient();
  const { panel, stepper, footer, wizard, storage } = create(client);

  assert.equal(stepper.findAll("stepper__step").length, 4);
  assert.ok(panel.findButton("Start discovery"));
  assert.equal(panel.textContent.includes("Living Room"), false, "mock candidates are absent before discovery");

  panel.findButton("Start discovery").dispatch("click");
  await settle();

  assert.deepEqual(client.calls.map(([operation]) => operation), ["discovery", "recommendations", "start"]);
  assert.equal(wizard.state.status, "loaded");
  assert.ok(panel.textContent.includes("ha-real-instance"), "real discovery response is rendered");
  assert.ok(panel.textContent.includes("snapshot-real"));
  assert.ok(storage.values.has("controlel.setup.draft.v1.entry-real"), "only the backend draft pointer is retained locally");
  assert.ok(footer.findButton("Continue"));
  assert.equal(footer.findButton("Activate"), null);
});

test("wizard saves an updated draft and validates without activation or runtime calls", async () => {
  const client = fakeClient();
  const { wizard } = create(client);
  await wizard.startDiscovery();

  wizard.state.draft.areaId = "living";
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
  wizard.state.dirty = true;

  await wizard.saveDraft();
  const update = client.calls.find(([operation]) => operation === "update")[1];
  assert.equal(update.expected_revision, 1);
  assert.deepEqual(update.settings, {
    zone_id: "living",
    zone_name: "living",
    sensor_id: "sensor-registry-id",
    sensor_name: "sensor.living_temperature",
  });
  assert.equal(update.selections.length, 3);
  assert.ok(update.selections.every((item) => item.user_confirmed));
  assert.equal(update.settings.source_enable, undefined, "frontend does not invent service settings");

  await wizard.validateDraft();
  assert.deepEqual(client.calls.map(([operation]) => operation), [
    "discovery", "recommendations", "start", "update", "validate",
  ]);
  assert.equal(client.calls.some(([operation]) => operation === "activate" || operation === "canonicalize"), false);
  assert.equal(client.calls.some(([operation]) => operation.startsWith("runtime") || operation.startsWith("service")), false);
});

test("wizard reopens the stored backend draft after real discovery", async () => {
  const client = fakeClient();
  const storage = memoryStorage({ "controlel.setup.draft.v1.entry-real": "draft-existing" });
  const { wizard } = create(client, storage);

  await wizard.startDiscovery();

  assert.deepEqual(client.calls.map(([operation]) => operation), ["discovery", "recommendations", "reopen"]);
  assert.equal(wizard.state.session.draft_id, "draft-existing");
});

test("wizard preserves authoritative settings outside the edited wizard fields", async () => {
  const existingSettings = {
    zone_id: "previous_zone",
    zone_name: "Previous zone",
    sensor_id: "externally-supplied-sensor",
    sensor_name: "External temperature sensor",
    target_temperature_celsius: 20.5,
    source_enable: {
      domain: "vendor_boiler",
      service: "grant_permission",
    },
    future_boiler_optimization: {
      curve: "adaptive",
      maximum_flow_temperature_celsius: 55,
    },
  };
  const client = fakeClient({ reopenOverrides: { settings: existingSettings } });
  const storage = memoryStorage({ "controlel.setup.draft.v1.entry-real": "draft-existing" });
  const { wizard } = create(client, storage);
  await wizard.startDiscovery();

  wizard.state.draft.areaId = "living";
  wizard.state.dirty = true;
  await wizard.saveDraft();

  const update = client.calls.find(([operation]) => operation === "update")[1];
  assert.deepEqual(update.settings, {
    ...existingSettings,
    zone_id: "living",
    zone_name: "living",
  });
  assert.deepEqual(update.settings.source_enable, existingSettings.source_enable);
  assert.deepEqual(update.settings.future_boiler_optimization, existingSettings.future_boiler_optimization);
  assert.equal(update.settings.sensor_id, existingSettings.sensor_id);
  assert.equal(update.settings.sensor_name, existingSettings.sensor_name);
  assert.deepEqual(wizard.state.session.settings, update.settings, "the saved backend session retains the full settings payload");
});

test("backend hydration clears an optimistic area omitted from the saved session", async () => {
  const client = fakeClient({
    updateOverrides: { settings: { future_backend_setting: "authoritative" } },
  });
  const { wizard } = create(client);
  await wizard.startDiscovery();

  wizard.state.draft.areaId = "living";
  wizard.state.dirty = true;
  await wizard.saveDraft();

  const update = client.calls.find(([operation]) => operation === "update")[1];
  assert.equal(update.settings.zone_id, "living", "the optimistic area was submitted");
  assert.equal(wizard.state.session.settings.zone_id, undefined);
  assert.equal(wizard.state.draft.areaId, null, "the backend response replaces optimistic UI state");
  assert.equal(wizard.state.dirty, false);
});

test("wizard shows backend discovery errors and never falls back to mock data", async () => {
  const client = fakeClient({ failDiscovery: true });
  const { panel, wizard } = create(client);

  await wizard.startDiscovery();

  assert.equal(wizard.state.status, "error");
  assert.ok(panel.textContent.includes("Setup discovery unavailable"));
  assert.ok(panel.textContent.includes("registry unavailable"));
  assert.equal(panel.textContent.includes("Living Room"), false);
  assert.equal(client.calls.some(([operation]) => operation === "start" || operation === "reopen"), false);
});

test("wizard shows draft update errors without replacing them with mock state", async () => {
  const client = fakeClient({ failUpdate: true });
  const { panel, wizard } = create(client);
  await wizard.startDiscovery();
  wizard.goToStep(4);
  wizard.state.draft.areaId = "living";
  wizard.state.dirty = true;

  await wizard.saveDraft();

  assert.equal(wizard.state.status, "error");
  assert.ok(panel.textContent.includes("Setup draft unavailable"));
  assert.ok(panel.textContent.includes("draft validation failed"));
  assert.equal(panel.textContent.includes("Living Room"), false);
  assert.equal(client.calls.filter(([operation]) => operation === "update").length, 1, "no silent fallback request is made");
});
