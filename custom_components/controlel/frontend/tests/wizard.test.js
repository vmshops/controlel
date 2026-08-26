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

function candidate(id, role, locator, domain, overrides = {}) {
  const base = {
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
  return { ...base, ...overrides, evidence: { ...base.evidence, ...(overrides.evidence || {}) } };
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
  failReopen = null,
  failUpdate = false,
  failValidation = false,
  reopenOverrides = {},
  updateOverrides = {},
  validateOverrides = {},
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
      if (failReopen) return Promise.reject(failReopen);
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
      if (failValidation) return Promise.reject(new Error("validation backend unavailable"));
      return Promise.resolve(session({ draft_revision: 2, ...validateOverrides }));
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
  assert.equal(update.preferred_area_id, "living");
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
  assert.equal(client.calls.find(([operation]) => operation === "validate")[1].preferred_area_id, "living");
  assert.equal(client.calls.some(([operation]) => operation === "activate" || operation === "canonicalize"), false);
  assert.equal(client.calls.some(([operation]) => operation.startsWith("runtime") || operation.startsWith("service")), false);
});

test("wizard reopens the stored backend draft after real discovery", async () => {
  const client = fakeClient();
  const storage = memoryStorage({ "controlel.setup.draft.v1.entry-real": "draft-existing" });
  const { panel, wizard } = create(client, storage);

  assert.ok(panel.findButton("Resume draft"), "the existing draft is offered explicitly");
  panel.findButton("Resume draft").dispatch("click");
  await settle();

  assert.deepEqual(client.calls.map(([operation]) => operation), ["discovery", "recommendations", "reopen"]);
  assert.equal(wizard.state.session.draft_id, "draft-existing");
  assert.equal(wizard.state.step, 4, "a resumed draft opens on its backend validation report");
  assert.equal(client.calls.some(([operation]) => operation === "start"), false, "resume never creates a duplicate draft");
});

test("wizard replaces a stale local draft pointer with a fresh backend draft", async () => {
  const missing = new Error("draft not found");
  missing.code = "not_found";
  const client = fakeClient({ failReopen: missing });
  const storage = memoryStorage({ "controlel.setup.draft.v1.entry-real": "draft-missing" });
  const { wizard } = create(client, storage);

  await wizard.startDiscovery();

  assert.equal(wizard.state.status, "loaded");
  assert.deepEqual(client.calls.map(([operation]) => operation), [
    "discovery", "recommendations", "reopen", "start",
  ]);
  assert.notEqual(wizard.state.session.draft_id, "draft-missing");
  assert.equal(storage.values.get("controlel.setup.draft.v1.entry-real"), wizard.state.session.draft_id);
  assert.equal(wizard.state.step, 1, "a replacement draft restarts the guided flow");
});

test("wizard candidate compatibility excludes diagnostics and unsupported domains", () => {
  const temperatureRole = W.PRIMARY_TEMPERATURE_ROLE;
  const sourceRole = W.SOURCE_ENABLE_TARGET_ROLE;
  const temperature = candidate("1".repeat(64), temperatureRole, "sensor.room_temperature", "sensor");
  const namedOnly = candidate("2".repeat(64), temperatureRole, "sensor.room_temp", "sensor", {
    capabilities: ["measurement.temperature.unverified"],
  });
  const own = candidate("3".repeat(64), temperatureRole, "sensor.controlel_zone_temperature", "sensor", {
    evidence: { platform: "controlel" },
  });
  const weather = candidate("4".repeat(64), sourceRole, "weather.home", "weather", {
    capabilities: ["command.custom_service_target.unverified"],
  });
  const source = candidate("5".repeat(64), sourceRole, "switch.boiler", "switch");

  assert.equal(W.isWizardCandidateCompatible(temperatureRole, temperature), true);
  assert.equal(W.isWizardCandidateCompatible(temperatureRole, namedOnly), false);
  assert.equal(W.isWizardCandidateCompatible(temperatureRole, own), false);
  assert.equal(W.isWizardCandidateCompatible(sourceRole, weather), false);
  assert.equal(W.isWizardCandidateCompatible(sourceRole, source), true);
});

test("selected room constrains the initial top three candidates and Show more reveals the rest", async () => {
  const client = fakeClient();
  const { panel, wizard } = create(client);
  await wizard.startDiscovery();
  const role = W.PRIMARY_TEMPERATURE_ROLE;
  const sensors = [
    candidate("1".repeat(64), role, "sensor.living_one", "sensor"),
    candidate("2".repeat(64), role, "sensor.office_one", "sensor", { area_id: "office", evidence: { area_id: "office" } }),
    candidate("3".repeat(64), role, "sensor.living_two", "sensor"),
    candidate("4".repeat(64), role, "sensor.living_three", "sensor"),
    candidate("5".repeat(64), role, "sensor.living_four", "sensor"),
  ];
  wizard.state.recommendations = [
    { role, recommended: sensors[1], alternatives: [sensors[2], sensors[0], sensors[3], sensors[4]], explicit_confirmation_required: true },
    ...recommendations().filter((item) => item.role !== role),
  ];
  wizard.state.draft.areaId = "living";
  wizard.goToStep(3);

  let sensorPanel = panel.findAll("panel")[0];
  assert.equal(sensorPanel.findAll("candidate").length, 3, "the initial list is capped at three local candidates");
  assert.equal(sensorPanel.textContent.includes("sensor.office_one"), false, "other-room candidates stay behind disclosure");
  assert.ok(sensorPanel.findButton("Show more (2)"));

  sensorPanel.findButton("Show more (2)").dispatch("click");
  sensorPanel = panel.findAll("panel")[0];
  assert.equal(sensorPanel.findAll("candidate").length, 5);
  assert.equal(sensorPanel.findAll("candidate").slice(0, 4).every((item) => item.textContent.includes("sensor.living_")), true);
  assert.ok(sensorPanel.findButton("Show fewer"));
});

test("one simple-switch selection derives and confirms both source bindings", async () => {
  const { panel, wizard } = create(fakeClient());
  await wizard.startDiscovery();
  wizard.goToStep(3);

  let sourcePanel = panel.findAll("panel")[1];
  const radio = Array.from(sourcePanel.walk()).find(
    (item) => item.tagName === "INPUT" && item.getAttribute("type") === "radio"
  );
  radio.dispatch("change");

  assert.equal(wizard.state.draft.selections[W.SOURCE_ENABLE_TARGET_ROLE], IDS.enable);
  assert.equal(wizard.state.draft.selections[W.SOURCE_DISABLE_TARGET_ROLE], IDS.disable);
  sourcePanel = panel.findAll("panel")[1];
  const confirmation = Array.from(sourcePanel.walk()).find(
    (item) => item.tagName === "INPUT" && item.getAttribute("type") === "checkbox"
  );
  confirmation.dispatch("change", { target: { checked: true } });
  assert.equal(wizard.state.draft.confirmations[W.SOURCE_ENABLE_TARGET_ROLE], true);
  assert.equal(wizard.state.draft.confirmations[W.SOURCE_DISABLE_TARGET_ROLE], true);
});

test("wizard entry reflects Ready and incomplete backend setup states without treating unknown as false", () => {
  const ready = create(fakeClient());
  ready.wizard.setEntryState({
    status: "loaded",
    readiness: { state: "ready", reason_code: null },
    error: null,
  });
  assert.ok(ready.panel.textContent.includes("Current backend setup state"));
  assert.ok(ready.panel.textContent.includes("Ready"));
  assert.ok(ready.panel.textContent.includes("does not mean a wizard draft was activated"));

  ready.wizard.setEntryState({
    status: "loaded",
    readiness: { state: "incomplete", reason_code: "SETUP_INCOMPLETE" },
    error: null,
  });
  assert.ok(ready.panel.textContent.includes("Not Ready"));
  assert.ok(ready.panel.textContent.includes("SETUP_INCOMPLETE"));
  assert.ok(ready.panel.findButton("Start discovery"), "incomplete setup is guided into the wizard");

  ready.wizard.setEntryState({
    status: "loaded",
    readiness: { state: "unknown", reason_code: "runtime_readiness_unknown" },
    error: null,
  });
  assert.ok(ready.panel.textContent.includes("Unknown"));
  assert.equal(ready.panel.textContent.includes("Not Ready"), false, "unknown is not presented as false");
});

test("wizard renders blocking backend validation as a clear Not Ready state", async () => {
  const { panel, wizard } = create(fakeClient());
  await wizard.startDiscovery();
  wizard.goToStep(4);

  assert.ok(panel.textContent.includes("Not Ready"));
  assert.ok(panel.textContent.includes("Blocking issues"));
  assert.equal(panel.findAll("validation-item--blocking").length, 1);
  assert.ok(panel.textContent.includes("target_temperature_celsius"), "the backend field path remains available");
  assert.ok(panel.textContent.includes("heating.invalid_setting"), "the stable technical code remains available");
  assert.equal(panel.textContent.includes("setup.heating.invalid_setting"), false, "the message key is not shown as user copy");
});

test("warning-only backend validation is Ready while warnings remain distinct", async () => {
  const warning = {
    code: "heating.ephemeral_custom_service_target",
    severity: "WARNING",
    path: ["bindings", W.SOURCE_ENABLE_TARGET_ROLE],
    module_role: W.SOURCE_ENABLE_TARGET_ROLE,
    message_key: "setup.heating.ephemeral_custom_service_target",
    parameters: {},
    evidence: { resolution_status: "EPHEMERAL" },
    suggested_action: "confirm_external_service_target_stability",
  };
  const client = fakeClient({
    validateOverrides: {
      incomplete: false,
      activation_ready: true,
      blocking_issue_count: 0,
      warning_count: 1,
      validation_issues: [warning],
    },
  });
  const { panel, wizard } = create(client);
  await wizard.startDiscovery();
  wizard.goToStep(4);
  await wizard.validateDraft();

  assert.ok(panel.textContent.includes("Ready"));
  assert.ok(panel.textContent.includes("not activated"));
  assert.ok(panel.textContent.includes("Warnings"));
  assert.equal(panel.findAll("validation-item--warning").length, 1);
  assert.equal(panel.findAll("validation-item--blocking").length, 0);
});

test("Ready backend validation is explicit and remains non-activating", async () => {
  const client = fakeClient({
    validateOverrides: {
      incomplete: false,
      activation_ready: true,
      blocking_issue_count: 0,
      warning_count: 0,
      validation_issues: [],
    },
  });
  const { panel, footer, wizard } = create(client);
  await wizard.startDiscovery();
  wizard.goToStep(4);
  await wizard.validateDraft();

  assert.ok(panel.textContent.includes("Ready"));
  assert.ok(panel.textContent.includes("The draft is Ready, but it is not activated."));
  assert.equal(footer.findButton("Activate"), null);
  assert.equal(client.calls.some(([operation]) => operation === "activate" || operation === "canonicalize"), false);
});

test("supported backend validation messages render in the selected language", async () => {
  globalThis.CI18N.setLanguage("cs");
  try {
    const { panel, wizard } = create(fakeClient());
    await wizard.startDiscovery();
    wizard.goToStep(4);

    assert.ok(panel.textContent.includes("Nastavení „target_temperature_celsius“ chybí nebo je neplatné."));
    assert.equal(panel.textContent.includes("setup.heating.invalid_setting"), false);
    assert.ok(panel.textContent.includes("heating.invalid_setting"), "the technical code is language-independent");
  } finally {
    globalThis.CI18N.setLanguage("en");
  }
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

test("returning to Discovery clears a stale update error without corrupting the draft", async () => {
  const client = fakeClient({ failUpdate: true });
  const { panel, wizard } = create(client);
  await wizard.startDiscovery();
  wizard.state.draft.areaId = "living";
  wizard.state.dirty = true;
  await wizard.saveDraft();

  wizard.goToStep(1);

  assert.equal(wizard.state.status, "loaded");
  assert.equal(wizard.state.session.draft_id.length > 0, true);
  assert.ok(panel.textContent.includes("Home Assistant discovery summary"));
  assert.equal(panel.textContent.includes("draft validation failed"), false);
});

test("wizard keeps backend validation failures visible", async () => {
  const client = fakeClient({ failValidation: true });
  const { panel, wizard } = create(client);
  await wizard.startDiscovery();
  wizard.goToStep(4);

  await wizard.validateDraft();

  assert.equal(wizard.state.status, "error");
  assert.ok(panel.textContent.includes("Setup draft unavailable"));
  assert.ok(panel.textContent.includes("validation backend unavailable"));
  assert.equal(client.calls.filter(([operation]) => operation === "validate").length, 1);
  assert.equal(client.calls.some(([operation]) => operation === "activate" || operation === "canonicalize"), false);
});
