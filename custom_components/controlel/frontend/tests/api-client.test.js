/*
 * Controlel frontend — Frontend API v1 adapter tests (Node, no dependencies).
 *
 * Run from the frontend/ directory:
 *   node --test tests/
 *
 * Covers:
 *   - successful API response mapping (all four domains)
 *   - null/unknown values stay unknown (never invented)
 *   - request failure / disconnected / timeout states
 *   - command / reported / physical states remain distinct
 *   - no silent mock fallback on real failure
 *   - HA environment detection
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

require("../api-client.js");

const CA_API = globalThis.CA_API;

// ------------------------------------------------------------- fixtures

function overviewRaw(overrides = {}) {
  return Object.assign({
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    system: {
      status: "active",
      operating_mode: "normal",
      operating_mode_reason: null,
      operating_mode_since: null,
    },
    modules: [
      { module_id: "heating", status: "active", reason: null },
    ],
    attention: [
      {
        attention_id: "att-1",
        severity: "warning",
        code: "SENSOR_CONFIRMATION_REQUIRED",
        scope: { type: "zone", zone_id: "zone.living-room" },
        summary: "Sensor confirmation required",
        first_seen_at: "2026-08-22T09:00:00+02:00",
      },
    ],
  }, overrides);
}

function heatingRaw(overrides = {}) {
  return Object.assign({
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    building: {
      demand_status: "no_heat_required",
      demand_reason_code: "ZONE_AT_TARGET",
      heat_source: {
        permission: "disabled",
        requested_command: null,
        command_outcome: null,
        reported_state: "DISABLED",
        physical_state: "unknown",
        last_decision_summary: null,
      },
    },
    zones: [
      {
        zone_id: "zone.living-room",
        name: "Living Room",
        current_temperature_c: 21.4,
        measurement_state: "fresh",
        measurement_age_seconds: 30,
        target_temperature_c: 21.0,
        demand_state: "no_heat_required",
        demand_reason_code: "ZONE_AT_TARGET",
        last_decision: null,
      },
    ],
  }, overrides);
}

function diagnosticsRaw(overrides = {}) {
  return Object.assign({
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    health: {
      runtime_status: "active",
      operating_mode: "normal",
      event_stream: { total_emitted: 3, retained: 3, dropped: 0 },
    },
    recent_events: [
      {
        event_id: "evt-1",
        timestamp: "2026-08-22T09:58:00+02:00",
        category: "zone",
        severity: "info",
        event_code: "ZONE_AT_TARGET",
        summary_code: "Zone at target",
        reason_code: null,
        scope: { type: "zone" },
        previous_state: null,
        new_state: null,
        command: null,
      },
      {
        event_id: "evt-2",
        timestamp: "2026-08-22T09:59:00+02:00",
        category: "source",
        severity: "warning",
        event_code: "COMMAND_FAILED",
        summary_code: "Command failed",
        reason_code: "SERVICE_ERROR",
        scope: { type: "source" },
        previous_state: "DISABLED",
        new_state: "DISABLED",
        command: { action: "enable", outcome: "failed" },
      },
    ],
    decision_trace: null,
  }, overrides);
}

function setupRaw(overrides = {}) {
  return Object.assign({
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    readiness: { state: "incomplete", reason_code: "SETUP_INCOMPLETE" },
    missing_configuration: [
      { code: "SENSOR_CONFIRMATION_REQUIRED", scope: { type: "zone" }, severity: "error" },
    ],
    validation_messages: [
      { code: "SENSOR_CONFIRMATION_REQUIRED", severity: "error", scope: { type: "zone" }, summary: "Confirm the primary sensor." },
    ],
  }, overrides);
}

// ------------------------------------------------------- fake connection

/**
 * A minimal stand-in for the HA connection. It records sent messages and
 * resolves one-shot results from a per-domain response map. `failTransport`
 * simulates a closed connection; `hang` simulates no response (timeout).
 */
function fakeConnection({ responses = {}, failTransport = false, hang = false } = {}) {
  const sent = [];
  return {
    sent,
    sendMessagePromise(message) {
      sent.push(message);
      if (failTransport) throw new Error("connection closed");
      if (hang) return new Promise(() => {}); // never respond → exercises the client timeout
      const domain = Object.keys(CA_API.COMMANDS).find((d) => CA_API.COMMANDS[d] === message.type);
      const resp = responses[domain];
      if (!resp) {
        return Promise.reject({ code: "not_found", message: "no provider" });
      }
      if (resp.__error) {
        return Promise.reject({ code: "error", message: resp.__error });
      }
      return Promise.resolve(resp);
    },
  };
}

function clientFor(connection, configEntryId = "entry-1", timeoutMs = 1000) {
  return CA_API.createFrontendApiClient({ connection, configEntryId, timeoutMs });
}

// ---------------------------------------------------------- normalizers

test("normalizeOverview maps a successful response and keeps nulls unknown", () => {
  const raw = overviewRaw({
    system: { status: "degraded", operating_mode: "degraded", operating_mode_reason: "module error", operating_mode_since: null },
    modules: [{ module_id: "heating", status: "error", reason: "heat source unavailable" }],
    attention: [],
  });
  const out = CA_API.normalizeOverview(raw);
  assert.equal(out.frontend_api_version, 1);
  assert.equal(out.system.status, "degraded");
  assert.equal(out.system.operating_mode_reason, "module error");
  assert.equal(out.system.operating_mode_since, null, "null stays null");
  assert.deepEqual(out.modules, [{ module_id: "heating", status: "error", reason: "heat source unavailable" }]);
  assert.deepEqual(out.attention, []);
});

test("normalizeHeating keeps command / reported / physical states distinct", () => {
  const raw = heatingRaw({
    building: {
      demand_status: "heat_required",
      demand_reason_code: "BELOW_TARGET",
      heat_source: {
        permission: "enabled",
        requested_command: "enable",
        command_outcome: "dispatched",
        reported_state: "ENABLED",
        physical_state: "unknown",
        last_decision_summary: { decision_id: "d-1", action: "enable_heating", observed_at: "2026-08-22T09:00:00+02:00", reason_code: "DEMAND" },
      },
    },
  });
  const out = CA_API.normalizeHeating(raw);
  const hs = out.building.heat_source;
  assert.equal(hs.permission, "enabled");
  assert.equal(hs.requested_command, "enable");
  assert.equal(hs.command_outcome, "dispatched");
  assert.equal(hs.reported_state, "ENABLED");
  assert.equal(hs.physical_state, "unknown", "physical state is never inferred");
  assert.equal(hs.last_decision_summary.decision_id, "d-1");
});

test("normalizeHeating keeps a null temperature unknown", () => {
  const raw = heatingRaw({
    zones: [{
      zone_id: "z", name: "Z", current_temperature_c: null, measurement_state: "missing",
      measurement_age_seconds: null, target_temperature_c: 21.0, demand_state: "indeterminate",
      demand_reason_code: null, last_decision: null,
    }],
  });
  const out = CA_API.normalizeHeating(raw);
  assert.equal(out.zones[0].current_temperature_c, null);
  assert.equal(out.zones[0].measurement_state, "missing");
  assert.equal(out.zones[0].demand_state, "indeterminate");
});

test("normalizeDiagnostics derives a display level from severity", () => {
  const out = CA_API.normalizeDiagnostics(diagnosticsRaw());
  const levels = out.recent_events.map((e) => e.level);
  assert.deepEqual(levels, ["basic", "detailed"]);
  assert.equal(out.recent_events[1].command.action, "enable");
  assert.equal(out.recent_events[1].command.outcome, "failed");
  assert.equal(out.decision_trace, null);
});

test("normalizeSetup maps readiness, missing config and validation", () => {
  const out = CA_API.normalizeSetup(setupRaw());
  assert.deepEqual(out.readiness, { state: "incomplete", reason_code: "SETUP_INCOMPLETE" });
  assert.equal(out.missing_configuration[0].code, "SENSOR_CONFIRMATION_REQUIRED");
  assert.equal(out.validation_messages[0].summary, "Confirm the primary sensor.");
});

test("normalizers reject an unsupported API version", () => {
  assert.throws(() => CA_API.normalizeOverview({ frontend_api_version: 2, system: {}, modules: [], attention: [] }), CA_API.ApiError);
});

test("normalizers reject a malformed shape", () => {
  assert.throws(() => CA_API.normalizeHeating({ frontend_api_version: 1, building: null, zones: [] }), CA_API.ApiError);
});

// --------------------------------------------------------------- client

test("client requires a connection and a config entry id", () => {
  assert.throws(() => CA_API.createFrontendApiClient({ connection: null, configEntryId: "e" }), CA_API.ApiError);
  assert.throws(() => CA_API.createFrontendApiClient({ connection: fakeConnection(), configEntryId: "" }), CA_API.ApiError);
});

test("client sends the right command with the config entry id", async () => {
  const connection = fakeConnection({ responses: { overview: overviewRaw() } });
  const client = clientFor(connection, "entry-42");
  await client.overview();
  assert.equal(connection.sent.length, 1);
  assert.equal(connection.sent[0].type, "controlel/frontend_api/v1/overview");
  assert.equal(connection.sent[0].config_entry_id, "entry-42");
});

test("client resolves a normalized model on success", async () => {
  const connection = fakeConnection({ responses: { heating: heatingRaw() } });
  const client = clientFor(connection);
  const data = await client.heating();
  assert.equal(data.building.heat_source.reported_state, "DISABLED");
  assert.equal(data.zones[0].current_temperature_c, 21.4);
});

test("successful one-shot results resolve without any subscription callback", async () => {
  const sent = [];
  const connection = {
    sendMessagePromise(message) {
      sent.push(message);
      return Promise.resolve(heatingRaw());
    },
  };
  assert.equal(connection.subscribeMessage, undefined, "no subscription API is available");

  const data = await clientFor(connection).heating();

  assert.equal(sent.length, 1);
  assert.equal(data.zones[0].current_temperature_c, 21.4);
});

test("client rejects with a typed error on a failed request", async () => {
  const connection = fakeConnection({ responses: { setup: { __error: "unavailable for this config entry" } } });
  const client = clientFor(connection);
  await assert.rejects(client.setup(), (err) => {
    assert.equal(err.kind, "error");
    assert.match(err.message, /unavailable for this config entry/);
    return true;
  });
});

test("client rejects with a disconnected error when the transport throws", async () => {
  const connection = fakeConnection({ failTransport: true });
  const client = clientFor(connection);
  await assert.rejects(client.overview(), (err) => {
    assert.equal(err.kind, "disconnected");
    return true;
  });
});

test("client rejects with a timeout error when no response arrives", async () => {
  const connection = fakeConnection({ hang: true });
  const client = clientFor(connection, "entry-1", 25);
  await assert.rejects(client.diagnostics(), (err) => {
    assert.equal(err.kind, "timeout");
    return true;
  });
});

// ------------------------------------------------------ environment detect

test("detectHaEnvironment is available with a connection and entry id", () => {
  const connection = { sendMessagePromise() {} };
  const win = { hass: { connection }, panelConfig: { config_entry_id: "entry-9" } };
  const env = CA_API.detectHaEnvironment(win);
  assert.equal(env.available, true);
  assert.equal(env.configEntryId, "entry-9");
  assert.equal(env.reason, null);
});

test("detectHaEnvironment uses supported panel properties over window globals", () => {
  const globalConnection = { sendMessagePromise() {} };
  const panelConnection = { sendMessagePromise() {} };
  const win = {
    hass: { connection: globalConnection },
    panelConfig: { config_entry_id: "global-entry" },
  };
  const env = CA_API.detectHaEnvironment(win, {
    hass: { connection: panelConnection },
    panel: { config: { config_entry_id: "panel-entry" } },
  });
  assert.equal(env.available, true);
  assert.equal(env.connection, panelConnection);
  assert.equal(env.configEntryId, "panel-entry");
});

test("detectHaEnvironment falls back to the ?entry= URL parameter", () => {
  const connection = { sendMessagePromise() {} };
  const win = { hass: { connection }, location: { search: "?entry=entry-url" } };
  const env = CA_API.detectHaEnvironment(win);
  assert.equal(env.available, true);
  assert.equal(env.configEntryId, "entry-url");
});

test("detectHaEnvironment is unavailable without a connection", () => {
  const env = CA_API.detectHaEnvironment({});
  assert.equal(env.available, false);
  assert.equal(env.reason, "no_ha_connection");
});

test("detectHaEnvironment rejects a subscription-only connection", () => {
  const env = CA_API.detectHaEnvironment({
    hass: { connection: { subscribeMessage() {} } },
    panelConfig: { config_entry_id: "entry-subscription-only" },
  });
  assert.equal(env.available, false);
  assert.equal(env.reason, "no_ha_connection");
});

test("detectHaEnvironment is unavailable without a config entry id", () => {
  const connection = { sendMessagePromise() {} };
  const env = CA_API.detectHaEnvironment({ hass: { connection } });
  assert.equal(env.available, false);
  assert.equal(env.reason, "missing_config_entry_id");
});

// ----------------------------------------------------------- data sources

test("real data source resolves loaded data on success", async () => {
  const connection = fakeConnection({ responses: { overview: overviewRaw() } });
  const ds = CA_API.createRealDataSource(clientFor(connection));
  const result = await ds.overview();
  assert.equal(result.status, "loaded");
  assert.equal(result.data.system.status, "active");
});

test("real data source reports an error and never falls back to mock", async () => {
  const connection = fakeConnection({ responses: { overview: { __error: "boom" } } });
  const ds = CA_API.createRealDataSource(clientFor(connection));
  const result = await ds.overview();
  assert.equal(result.status, "error");
  assert.equal(result.data, undefined, "no mock data is substituted");
  assert.equal(result.error.kind, "error");
});

test("demo data source resolves mock-derived models", async () => {
  const mock = {
    app: { lastUpdated: "2026-08-21 10:15" },
    modules: [{ id: "heating", state: "incomplete" }],
    issues: [{ severity: "warning", code: "SETUP_INCOMPLETE", message: "incomplete" }],
    heating: {
      zone: { name: "Living Room" },
      currentTemperature: { value: "21.4" },
      targetTemperature: { value: "21.0" },
      demand: { state: "idle" },
      heatSource: { state: "unknown" },
      status: { state: "incomplete", reason: "SETUP_INCOMPLETE" },
    },
    activity: [{ id: "e1", at: "2026-08-21 09:30", level: "basic", category: "setup", title: "T", reasonCodes: ["X"] }],
  };
  const ds = CA_API.createDemoDataSource(mock);
  const [ov, heat, diag, setup] = await Promise.all([ds.overview(), ds.heating(), ds.diagnostics(), ds.setup()]);
  assert.equal(ov.status, "loaded");
  assert.equal(ov.data.system.status, "degraded", "incomplete mock maps to degraded");
  assert.equal(heat.data.zones[0].current_temperature_c, 21.4);
  assert.equal(heat.data.building.heat_source.physical_state, "unknown");
  assert.equal(diag.data.recent_events[0].level, "basic");
  assert.equal(setup.data.readiness.state, "incomplete");
});

test("mockToModels keeps unknown heat source physical state unknown", () => {
  const models = CA_API.mockToModels({ heating: { heatSource: { state: "unknown" } } });
  assert.equal(models.heating.building.heat_source.physical_state, "unknown");
  assert.equal(models.heating.building.heat_source.permission, "disabled");
});

// ------------------------------------------------------ setup wizard client

function discoveryRaw() {
  return {
    snapshot_id: "snapshot-real",
    provider: "home_assistant",
    provider_instance_id: "ha-instance-real",
    captured_at: "2026-08-24T12:00:00Z",
    content_fingerprint: "f".repeat(64),
    object_counts: { "home_assistant.area": 1, "home_assistant.entity": 2 },
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

function setupWriteConnection(handler) {
  const sent = [];
  return {
    sent,
    sendMessagePromise(message) {
      sent.push(message);
      return handler(message);
    },
  };
}

function canonicalDraftRaw(revision) {
  return {
    schema_version: 3,
    draft_id: "draft-real",
    revision,
    base_active_revision_id: null,
    base_active_generation: 0,
    heating: { global: {}, zones: [], heat_sources: [], heat_delivery: [] },
    diagnostics: {},
    notifications: {},
  };
}

test("setup wizard client sends read-only discovery through Setup API v1", async () => {
  const connection = setupWriteConnection((message) => Promise.resolve({
    setup_write_api_version: 1,
    operation: "discovery",
    result: discoveryRaw(),
  }));
  const client = CA_API.createSetupWizardClient({ connection, configEntryId: "entry-setup" });

  const snapshot = await client.discover({ snapshot_id: "snapshot-real", captured_at: "2026-08-24T12:00:00Z" });

  assert.equal(snapshot.provider_instance_id, "ha-instance-real");
  assert.equal(snapshot.object_counts["home_assistant.area"], 1);
  assert.deepEqual(connection.sent, [{
    type: "controlel/setup/write/v1/discovery",
    config_entry_id: "entry-setup",
    snapshot_id: "snapshot-real",
    captured_at: "2026-08-24T12:00:00Z",
  }]);
});

test("setup wizard client exposes the complete canonical-v3 lifecycle and preserves backend errors", async () => {
  const connection = setupWriteConnection(() => Promise.reject({
    code: "setup_conflict",
    message: "draft revision conflict",
  }));
  const client = CA_API.createSetupWizardClient({ connection, configEntryId: "entry-setup" });

  assert.deepEqual(Object.keys(client).sort(), [
    "abandonDraft", "activateRevision", "canonicalizeDraft", "defaults", "discover", "editDraft", "listDrafts",
    "readActive", "recommendations", "reopenDraft", "startDraft", "updateDraft", "validateDraft",
  ]);
  await assert.rejects(
    client.updateDraft({ draft_id: "draft-1" }),
    (error) => error instanceof CA_API.ApiError && error.code === "setup_conflict" && error.message === "draft revision conflict"
  );
  assert.equal(connection.sent.length, 1, "no fallback or retry request is sent");
});

test("setup wizard client loads provenance defaults and abandons one exact canonical-v3 draft", async () => {
  const connection = setupWriteConnection((message) => {
    const operation = message.type.endsWith("/defaults") ? "defaults" : "abandon";
    return Promise.resolve({
      ...(operation === "defaults"
        ? { setup_write_api_version: 1 }
        : { canonical_configuration_api_version: 3 }),
      operation,
      result: operation === "defaults"
        ? {
            settings: { target_temperature_celsius: 21 },
            simple_switch: { source_control_mode: "simple" },
            core_version: "0.15.0",
            integration_version: "0.13.0",
          }
        : { draft_id: message.draft_id, abandoned_revision: message.expected_revision },
    });
  });
  const client = CA_API.createSetupWizardClient({ connection, configEntryId: "entry-setup" });

  const defaults = await client.defaults();
  const abandoned = await client.abandonDraft({ draft_id: "draft-real", expected_revision: 2 });

  assert.equal(defaults.settings.target_temperature_celsius, 21);
  assert.equal(defaults.core_version, "0.15.0");
  assert.deepEqual(abandoned, { draft_id: "draft-real", abandoned_revision: 2 });
  assert.equal(connection.sent[0].type, "controlel/setup/write/v1/defaults");
  assert.equal(connection.sent[1].type, "controlel/configuration/v3/abandon");
  assert.equal(connection.sent[1].expected_revision, 2);
});

test("setup wizard client sends canonical-v3 start and optimistic update requests", async () => {
  const connection = setupWriteConnection((message) => {
    const operation = message.type.endsWith("/start") ? "start" : "update";
    return Promise.resolve({
      canonical_configuration_api_version: 3,
      operation,
      result: canonicalDraftRaw(operation === "start" ? 1 : 2),
    });
  });
  const client = CA_API.createSetupWizardClient({ connection, configEntryId: "entry-setup" });

  const created = await client.startDraft({
    draft_id: "draft-real",
    created_at: "2026-08-24T12:00:00Z",
    snapshot_id: "snapshot-real",
    bindings: { topology: {} },
  });
  const updated = await client.updateDraft({
    draft_id: "draft-real",
    expected_revision: 1,
    updated_at: "2026-08-24T12:01:00Z",
    configuration_scopes: { heating: {}, diagnostics: {}, notifications: {} },
  });

  assert.equal(created.revision, 1);
  assert.equal(updated.revision, 2);
  assert.equal(connection.sent[0].type, "controlel/configuration/v3/start");
  assert.equal(connection.sent[1].type, "controlel/configuration/v3/update");
  assert.equal(connection.sent[1].expected_revision, 1);
  assert.deepEqual(connection.sent[1].configuration_scopes, { heating: {}, diagnostics: {}, notifications: {} });
  assert.ok(connection.sent.every((message) => message.config_entry_id === "entry-setup"));
});

test("canonical validation, canonicalization, and activation remain distinct requests", async () => {
  const connection = setupWriteConnection((message) => {
    const operation = message.type.split("/").at(-1);
    const result = operation === "validate"
      ? { report_id: "report-1", draft_id: "draft-real", draft_revision: 2, activation_ready: true, issue_codes: [], reference_health: [] }
      : operation === "canonicalize"
        ? { ...canonicalDraftRaw(1), revision_id: "canonical-1", semantic_configuration_fingerprint: "a".repeat(64) }
        : { generation: 1, canonical_revision_id: "canonical-1" };
    return Promise.resolve({ canonical_configuration_api_version: 3, operation, result });
  });
  const client = CA_API.createSetupWizardClient({ connection, configEntryId: "entry-setup" });

  await client.validateDraft({ draft_id: "draft-real" });
  await client.canonicalizeDraft({ draft_id: "draft-real" });
  await client.activateRevision({ revision_id: "canonical-1" });

  assert.deepEqual(connection.sent.map((message) => message.type), [
    "controlel/configuration/v3/validate",
    "controlel/configuration/v3/canonicalize",
    "controlel/configuration/v3/activate",
  ]);
});

// ------------------------------------------------------ setup write client (water)

function setupSessionRaw(revision) {
  return {
    draft_id: "draft-real",
    draft_revision: revision,
    module_instance_id: "main-water",
    incomplete: true,
    activation_ready: false,
    validation_status: "CURRENT",
    validation_report_id: "report-real",
    blocking_issue_count: 1,
    warning_count: 0,
    settings: {},
    selections: [],
    recommendations: [],
    validation_issues: [],
    discovery: discoveryRaw(),
    canonical_revision_id: null,
    active_revision_id: null,
    legacy_configuration: { present: false, conversion_available: false, silently_merged: false, reason_code: null },
  };
}

test("normalizeWaterSafety preserves null sensor condition", () => {
  const model = CA_API.normalizeWaterSafety({
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    state: "DISABLED",
    assessment_status: "DISABLED",
    sensor_condition: null,
    area_name: null,
    zone_name: null,
    active_incident: false,
    incident_silenced: false,
    processing_enabled: false,
    owned_siren_count: 0,
    last_siren_command_outcome: null,
    actions_available: [],
  });
  assert.equal(model.sensor_condition, null);
});

test("setup write client includes module_key for water safety", async () => {
  const connection = setupWriteConnection((message) => Promise.resolve({
    setup_write_api_version: 1,
    operation: "discovery",
    result: discoveryRaw(),
  }));
  const client = CA_API.createSetupWriteClient({
    connection,
    configEntryId: "entry-setup",
    moduleKey: "water_safety",
  });

  await client.discover({ snapshot_id: "snapshot-water", captured_at: "2026-08-24T12:00:00Z" });
  assert.equal(connection.sent[0].module_key, "water_safety");
});

test("setup write client exposes lifecycle operations for water safety", async () => {
  const connection = setupWriteConnection((message) => Promise.resolve({
    setup_write_api_version: 1,
    operation: message.type.endsWith("/canonicalize") ? "canonicalize" : "activate",
    result: setupSessionRaw(3),
  }));
  const client = CA_API.createSetupWriteClient({
    connection,
    configEntryId: "entry-setup",
    moduleKey: "water_safety",
  });

  assert.equal(typeof client.canonicalizeDraft, "function");
  assert.equal(typeof client.activateDraft, "function");
});
