/*
 * Controlel frontend — application shell behavior tests (Node, no deps).
 *
 * Run from the frontend/ directory:
 *   node --test tests/
 *
 * Covers:
 *   - navigation (route parsing, view switching, nav rendering)
 *   - truthful UI states: loading / loaded / error (disconnected)
 *   - null/unknown values render as unknown (never invented)
 *   - command / reported / physical states remain distinct
 *   - no silent mock fallback on a failed real request
 *   - explicit demo mode and unavailable mode
 *   - setup navigation remains separate from runtime views
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { Element, documentStub } = require("./dom-stub");

// The frontend scripts expect a `document` global; provide the stub first.
global.document = documentStub;

// i18n.js first: components.js / app.js / wizard.js resolve UI strings
// through the shared CI18N instance. In Node (no window/localStorage) the
// default instance resolves to English, so the canonical English assertions
// below exercise the real translation path.
require("../i18n.js");
require("../mock-app-data.js");
require("../api-client.js");
require("../components.js");
require("../wizard.js");
require("../app.js");

const CW = globalThis.CW;
const CA = globalThis.CA;
const CA_API = globalThis.CA_API;
const DATA = globalThis.MOCK_APP_DATA;

// ------------------------------------------------------------- fixtures

function overviewRaw() {
  return {
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    system: { status: "active", operating_mode: "normal", operating_mode_reason: null, operating_mode_since: null },
    modules: [{ module_id: "heating", status: "active", reason: null }],
    attention: [
      { attention_id: "a1", severity: "warning", code: "SENSOR_CONFIRMATION_REQUIRED", scope: { type: "zone" }, summary: "Confirm the primary sensor.", first_seen_at: null },
    ],
  };
}

function heatingRaw() {
  return {
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
    zones: [{
      zone_id: "zone.living-room",
      name: "Living Room",
      current_temperature_c: 21.4,
      measurement_state: "fresh",
      measurement_age_seconds: 30,
      target_temperature_c: 21.0,
      demand_state: "no_heat_required",
      demand_reason_code: "ZONE_AT_TARGET",
      last_decision: null,
    }],
  };
}

function diagnosticsRaw() {
  return {
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    health: { runtime_status: "active", operating_mode: "normal", event_stream: { total_emitted: 2, retained: 2, dropped: 0 } },
    recent_events: [
      { event_id: "e1", timestamp: "2026-08-22T09:58:00+02:00", category: "zone", severity: "info", event_code: "ZONE_AT_TARGET", summary_code: "Zone at target", reason_code: null, scope: { type: "zone" }, previous_state: null, new_state: null, command: null },
      { event_id: "e2", timestamp: "2026-08-22T09:59:00+02:00", category: "source", severity: "warning", event_code: "COMMAND_FAILED", summary_code: "Command failed", reason_code: "SERVICE_ERROR", scope: { type: "source" }, previous_state: "DISABLED", new_state: "DISABLED", command: { action: "enable", outcome: "failed" } },
    ],
    decision_trace: null,
  };
}

function setupRaw() {
  return {
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    readiness: { state: "incomplete", reason_code: "SETUP_INCOMPLETE" },
    missing_configuration: [{ code: "SENSOR_CONFIRMATION_REQUIRED", scope: { type: "zone" }, severity: "error" }],
    validation_messages: [{ code: "SENSOR_CONFIRMATION_REQUIRED", severity: "error", scope: { type: "zone" }, summary: "Confirm the primary sensor." }],
  };
}

function fullResponses() {
  return { overview: overviewRaw(), heating: heatingRaw(), diagnostics: diagnosticsRaw(), setup: setupRaw() };
}

// ------------------------------------------------------- fake connection

function fakeConnection({ responses = {}, failTransport = false } = {}) {
  return {
    sendMessagePromise(message) {
      if (failTransport) throw new Error("connection closed");
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

// ------------------------------------------------------------- app builder

function buildApp({ mode = "real", responses = fullResponses(), failTransport = false, withDemo = true } = {}) {
  const connection = fakeConnection({ responses, failTransport });
  const client = CA_API.createFrontendApiClient({ connection, configEntryId: "entry-1", timeoutMs: 1000 });
  const dataSource = CA_API.createRealDataSource(client);

  const root = new Element("div");
  const navRoot = new Element("div"); navRoot.id = "app-nav";
  const viewRoot = new Element("main"); viewRoot.id = "view-root";
  const wizardRoot = new Element("div"); wizardRoot.id = "wizard-view";
  const topbar = new Element("span"); topbar.id = "topbar-status";
  const modeEl = new Element("p"); modeEl.id = "app-mode";
  root.append(navRoot, topbar, modeEl, viewRoot, wizardRoot);
  documentStub._root = root;

  const app = CA.createApp({
    mode,
    dataSource,
    demoFactory: withDemo ? () => CA_API.createDemoDataSource(DATA) : null,
    navRoot,
    viewRoot,
    wizardRoot,
    topbarStatusRoot: topbar,
    modeRoot: modeEl,
    renderRoot: root,
  });
  return { app, root, navRoot, viewRoot, wizardRoot, topbar, modeEl, connection };
}

/** Await all in-flight domain loads so the view has re-rendered. */
async function settle(app) {
  const pending = Object.values(app.state.domains).map((d) => d.inflight).filter(Boolean);
  if (pending.length) await Promise.all(pending);
}

// ---------------------------------------------------------------- navigation

test("parseRoute maps known hashes to routes and falls back to overview", () => {
  assert.equal(CA.parseRoute("#/heating"), "heating");
  assert.equal(CA.parseRoute("#/diagnostics?x=1"), "diagnostics");
  assert.equal(CA.parseRoute("#/setup"), "setup");
  assert.equal(CA.parseRoute("#/bogus"), CA.DEFAULT_ROUTE);
  assert.equal(CA.parseRoute(""), CA.DEFAULT_ROUTE);
  assert.equal(CA.parseRoute(null), CA.DEFAULT_ROUTE);
});

test("navigation renders the requested view and marks the current nav item", async () => {
  const { app, navRoot, viewRoot } = buildApp();

  app.navigate("modules");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("Modules"));
  const current = navRoot.findAll("app-nav__item--current");
  assert.equal(current.length, 1);
  assert.equal(current[0].getAttribute("data-route"), "modules");
  assert.equal(current[0].getAttribute("aria-current"), "page");

  app.navigate("heating");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("Heating"));
  assert.ok(viewRoot.textContent.includes("Current temperature"));
});

test("navigating to setup shows the wizard container and the readiness view", async () => {
  const { app, viewRoot, wizardRoot } = buildApp();
  app.navigate("setup");
  await settle(app);
  assert.equal(viewRoot.hidden, false, "readiness view is shown");
  assert.equal(wizardRoot.hidden, false, "wizard is shown below the readiness view");
  assert.ok(viewRoot.textContent.includes("Readiness"));
  app.navigate("overview");
  await settle(app);
  assert.equal(viewRoot.hidden, false);
  assert.equal(wizardRoot.hidden, true);
});

test("unknown routes fall back to the default route", async () => {
  const { app, viewRoot } = buildApp();
  app.navigate("does-not-exist");
  await settle(app);
  assert.equal(app.state.route, CA.DEFAULT_ROUTE);
  assert.ok(viewRoot.textContent.includes("Overview"));
});

test("clicking a navigation item navigates", async () => {
  const { app, navRoot, viewRoot } = buildApp();
  const item = navRoot.findAll("app-nav__item").find((b) => b.getAttribute("data-route") === "diagnostics");
  assert.ok(item, "diagnostics nav item exists");
  item.dispatch("click");
  await settle(app);
  assert.equal(app.state.route, "diagnostics");
  assert.ok(viewRoot.textContent.includes("Diagnostics / Activity"));
});

test("topbar shows the real setup readiness state", async () => {
  const { app, topbar } = buildApp();
  app.navigate("overview");
  await settle(app);
  assert.ok(topbar.textContent.includes("Incomplete"), "readiness state shown in topbar");
});

// ------------------------------------------------------------- truthful states

test("a view shows a loading state before data arrives", () => {
  const { app, viewRoot } = buildApp();
  app.navigate("overview");
  // Synchronously after navigate, the domains have not settled yet.
  assert.ok(viewRoot.textContent.includes("Loading…"), "loading panel shown");
});

test("a view shows loaded data after the request resolves", async () => {
  const { app, viewRoot, connection } = buildApp();
  assert.equal(connection.subscribeMessage, undefined, "rendering does not depend on a subscription callback");
  app.navigate("overview");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("Living Room") === false, "overview has no zone name");
  assert.ok(viewRoot.textContent.includes("heating"), "module id rendered");
  assert.ok(viewRoot.textContent.includes("Confirm the primary sensor."), "attention rendered");
});

test("a failed request shows an error state with a retry action (no mock fallback)", async () => {
  const { app, viewRoot } = buildApp({ responses: { overview: { __error: "config entry is not loaded" } } });
  app.navigate("overview");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("Unavailable"), "error state shown");
  assert.ok(viewRoot.textContent.includes("config entry is not loaded"), "backend error surfaced");
  assert.ok(viewRoot.findButton("Retry"), "retry action offered");
  // The mock zone name must NOT appear as a silent fallback.
  assert.ok(!viewRoot.textContent.includes("Living Room"), "no mock data substituted");
});

test("retry re-issues the request and recovers when it then succeeds", async () => {
  const responses = { overview: { __error: "first call fails" } };
  const { app, viewRoot } = buildApp({ responses });
  app.navigate("overview");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("Unavailable"));

  // Make the next call succeed.
  responses.overview = overviewRaw();
  viewRoot.findButton("Retry").dispatch("click");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("heating"), "recovered to loaded data");
});

test("unknown/null backend values render as Unknown, not a guessed value", async () => {
  const { app, viewRoot } = buildApp({
    responses: {
      ...fullResponses(),
      heating: {
        ...heatingRaw(),
        zones: [{
          zone_id: "z", name: "Zone", current_temperature_c: null, measurement_state: "missing",
          measurement_age_seconds: null, target_temperature_c: 21.0, demand_state: "indeterminate",
          demand_reason_code: null, last_decision: null,
        }],
      },
    },
  });
  app.navigate("heating");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("Unknown"), "null temperature shown as Unknown");
  assert.ok(viewRoot.textContent.includes("Missing"), "measurement state shown");
  assert.ok(viewRoot.textContent.includes("Indeterminate"), "indeterminate demand shown");
});

test("heat source permission, command, reported and physical states stay distinct", async () => {
  const { app, viewRoot } = buildApp({
    responses: {
      ...fullResponses(),
      heating: {
        ...heatingRaw(),
        building: {
          demand_status: "heat_required",
          demand_reason_code: "BELOW_TARGET",
          heat_source: {
            permission: "enabled",
            requested_command: "enable",
            command_outcome: "dispatched",
            reported_state: "ENABLED",
            physical_state: "unknown",
            last_decision_summary: null,
          },
        },
      },
    },
  });
  app.navigate("heating");
  await settle(app);
  const text = viewRoot.textContent;
  assert.ok(text.includes("Permission"), "permission field present");
  assert.ok(text.includes("enabled"), "permission value shown");
  assert.ok(text.includes("Requested command"), "requested command field present");
  assert.ok(text.includes("Command outcome"), "command outcome field present");
  assert.ok(text.includes("Reported state"), "reported state field present");
  assert.ok(text.includes("Physical state"), "physical state field present");
  assert.ok(text.includes("Unknown (not reported)"), "physical state is not inferred");
});

test("diagnostics shows health, level filtering and the activity list", async () => {
  const { app, viewRoot } = buildApp();
  app.navigate("diagnostics");
  await settle(app);

  assert.ok(viewRoot.textContent.includes("Runtime status"), "health section");
  assert.ok(viewRoot.textContent.includes("Events emitted"), "event stream health");

  // Default level is basic → only the info event is shown.
  let rows = viewRoot.findAll("activity-row");
  assert.equal(rows.length, 1, "basic level shows only basic events");

  // Switch to debug → both events shown.
  viewRoot.findButton("Debug").dispatch("click");
  await settle(app);
  rows = viewRoot.findAll("activity-row");
  assert.equal(rows.length, 2, "debug level shows all events");
});

test("settings reflects the real readiness state and keeps placeholders", async () => {
  const { app, viewRoot } = buildApp();
  app.navigate("settings");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("Heating configuration"));
  assert.ok(viewRoot.textContent.includes("Incomplete"), "real readiness state on the heating row");
  assert.ok(viewRoot.textContent.includes("Notifications"), "placeholder row kept");
  assert.ok(viewRoot.findButton("Continue setup"), "links to setup");
});

test("setup view shows real readiness, missing config and validation", async () => {
  const { app, viewRoot } = buildApp();
  app.navigate("setup");
  await settle(app);
  assert.ok(viewRoot.textContent.includes("Incomplete"), "readiness state");
  assert.ok(viewRoot.textContent.includes("SETUP_INCOMPLETE"), "reason code");
  assert.ok(viewRoot.textContent.includes("SENSOR_CONFIRMATION_REQUIRED"), "missing configuration");
  assert.ok(viewRoot.textContent.includes("Confirm the primary sensor."), "validation message");
});

// ------------------------------------------------------------- demo / mode

test("demo mode renders mock-derived data when explicitly enabled", async () => {
  // Build a demo-mode app directly.
  const ds = CA_API.createDemoDataSource(DATA);
  const root = new Element("div");
  const navRoot = new Element("div"); navRoot.id = "app-nav";
  const vRoot = new Element("main"); vRoot.id = "view-root";
  const wRoot = new Element("div"); wRoot.id = "wizard-view";
  const topbar = new Element("span"); topbar.id = "topbar-status";
  const mEl = new Element("p"); mEl.id = "app-mode";
  root.append(navRoot, topbar, mEl, vRoot, wRoot);
  documentStub._root = root;
  const demoApp = CA.createApp({ mode: "demo", dataSource: ds, demoFactory: null, navRoot, viewRoot: vRoot, wizardRoot: wRoot, topbarStatusRoot: topbar });
  demoApp.navigate("heating");
  await settle(demoApp);
  assert.ok(vRoot.textContent.includes("Living Room"), "demo zone rendered");
  assert.ok(vRoot.textContent.includes("21.4"), "demo temperature rendered");
  assert.ok(mEl.textContent.includes("Demo mode"), "mode label reflects demo");
});

test("unavailable mode offers an explicit demo action and never shows mock data", async () => {
  const root = new Element("div");
  const navRoot = new Element("div"); navRoot.id = "app-nav";
  const vRoot = new Element("main"); vRoot.id = "view-root";
  const wRoot = new Element("div"); wRoot.id = "wizard-view";
  const topbar = new Element("span"); topbar.id = "topbar-status";
  const mEl = new Element("p"); mEl.id = "app-mode";
  root.append(navRoot, topbar, mEl, vRoot, wRoot);
  documentStub._root = root;

  const app = CA.createApp({
    mode: "unavailable",
    dataSource: null,
    demoFactory: () => CA_API.createDemoDataSource(DATA),
    navRoot, viewRoot: vRoot, wizardRoot: wRoot, topbarStatusRoot: topbar,
  });

  assert.ok(vRoot.textContent.includes("Disconnected"), "disconnected state shown");
  assert.ok(vRoot.findButton("Enable demo mode (mock data)"), "explicit demo action offered");
  assert.ok(!vRoot.textContent.includes("Living Room"), "no mock data shown by default");

  // Enabling demo is an explicit user action.
  vRoot.findButton("Enable demo mode (mock data)").dispatch("click");
  app.navigate("heating");
  await settle(app);
  assert.ok(vRoot.textContent.includes("Living Room"), "demo data shown after explicit enable");
  assert.ok(vRoot.textContent.includes("21.4"), "demo temperature shown");
});

// ------------------------------------------------------- pure logic / mapping

test("metaOf maps known states and falls back to neutral Unknown", () => {
  assert.deepEqual(CA.metaOf(CA.SYSTEM_STATUS_META, "active"), { label: "Active", tone: "positive" });
  assert.deepEqual(CA.metaOf(CA.READINESS_META, "incomplete"), { label: "Incomplete", tone: "warning" });
  assert.deepEqual(CA.metaOf(CA.DEMAND_META, "indeterminate"), { label: "Indeterminate", tone: "warning" });
  assert.deepEqual(CA.metaOf(CA.SYSTEM_STATUS_META, null), { label: "Unknown", tone: "neutral" });
  assert.equal(CA.metaOf(CA.SYSTEM_STATUS_META, "weird").tone, "neutral");
});

test("toModuleCard maps a real module to the card shape", () => {
  const card = CA.toModuleCard({ module_id: "heating", status: "active", reason: null });
  assert.equal(card.id, "heating");
  assert.equal(card.state, "active");
  assert.deepEqual(card.primaryAction, { label: "Open Heating", route: "heating" });

  const errCard = CA.toModuleCard({ module_id: "heating", status: "error", reason: "boom" });
  assert.equal(errCard.state, "error");
  assert.deepEqual(errCard.primaryAction, { label: "Review issues", route: "diagnostics" });
});

test("toActivityEvent maps a real event and keeps the command distinct", () => {
  const e = CA.toActivityEvent({
    event_id: "e2", timestamp: "2026-08-22T09:59:00+02:00", category: "source", severity: "warning",
    event_code: "COMMAND_FAILED", summary_code: "Command failed", reason_code: "SERVICE_ERROR",
    scope: { type: "source" }, previous_state: "DISABLED", new_state: "DISABLED",
    command: { action: "enable", outcome: "failed" }, level: "detailed",
  });
  assert.equal(e.id, "e2");
  assert.equal(e.level, "detailed");
  assert.deepEqual(e.reasonCodes, ["COMMAND_FAILED", "SERVICE_ERROR"]);
  assert.deepEqual(e.metadata.command, { action: "enable", outcome: "failed" });
});

test("filterEvents applies the selected maximum display level", () => {
  const events = [
    { level: "basic" }, { level: "basic" }, { level: "detailed" }, { level: "debug" },
  ];
  assert.equal(CA.filterEvents(events, "basic").length, 2);
  assert.equal(CA.filterEvents(events, "detailed").length, 3);
  assert.equal(CA.filterEvents(events, "debug").length, 4);
});

test("visibleItems hides hidden items and sorts by order", () => {
  const items = [
    { id: "b", order: 2 },
    { id: "a", order: 1 },
    { id: "x", order: 0, hidden: true },
  ];
  assert.deepEqual(CA.visibleItems(items).map((i) => i.id), ["a", "b"]);
});

// ------------------------------------------------------- reusable components

test("stateMeta maps every module state to a label and tone", () => {
  assert.deepEqual(CW.stateMeta("active"), { label: "Active", tone: "positive" });
  assert.deepEqual(CW.stateMeta("incomplete"), { label: "Incomplete setup", tone: "warning" });
  assert.deepEqual(CW.stateMeta("attention"), { label: "Needs attention", tone: "negative" });
  assert.deepEqual(CW.stateMeta("disabled"), { label: "Disabled", tone: "neutral" });
  assert.deepEqual(CW.stateMeta("not_configured"), { label: "Not configured", tone: "neutral" });
  // Real API vocabulary.
  assert.deepEqual(CW.stateMeta("error"), { label: "Error", tone: "negative" });
  assert.deepEqual(CW.stateMeta("inactive"), { label: "Inactive", tone: "neutral" });
});

test("unknown states render neutrally instead of being guessed", () => {
  const meta = CW.stateMeta("something-new");
  assert.equal(meta.tone, "neutral");
  assert.equal(meta.label, "something-new");
});

test("pageHeader renders title, subtitle, badges and actions", () => {
  const node = CW.pageHeader({
    title: "T",
    subtitle: "S",
    badges: [CW.badge("B", "info")],
    actions: [CW.el("button", { class: "btn" }, "A")],
  });
  assert.ok(node.textContent.includes("T"));
  assert.ok(node.textContent.includes("S"));
  assert.ok(node.findAll("badge")[0].textContent.includes("B"));
  assert.ok(node.findButton("A"));
});

test("section renders title, lead, children and actions", () => {
  const node = CW.section({
    title: "Title",
    lead: "Lead",
    children: CW.el("p", {}, "Body"),
    actions: [CW.el("button", { class: "btn" }, "Act")],
  });
  assert.ok(node.textContent.includes("Title"));
  assert.ok(node.textContent.includes("Lead"));
  assert.ok(node.textContent.includes("Body"));
  assert.ok(node.findButton("Act"));
});

test("metricCard renders label, value, unit and sub", () => {
  const node = CW.metricCard({ label: "Temp", value: "21.4", unit: "°C", sub: "reported" });
  assert.ok(node.textContent.includes("Temp"));
  assert.ok(node.textContent.includes("21.4"));
  assert.ok(node.textContent.includes("°C"));
  assert.ok(node.textContent.includes("reported"));
});

test("issuePanel renders issues and an empty variant", () => {
  const withIssues = CW.issuePanel({
    title: "Issues",
    issues: [{ severity: "warning", code: "X", message: "Something" }],
  });
  assert.ok(withIssues.textContent.includes("Something"));
  assert.ok(withIssues.textContent.includes("X"));

  const empty = CW.issuePanel({ title: "Issues", issues: [] });
  assert.ok(empty.textContent.includes("No issues reported."));
});

test("emptyState renders title, message and optional action", () => {
  const node = CW.emptyState({
    title: "Nothing here",
    message: "Add something",
    action: CW.el("button", { class: "btn" }, "Add"),
  });
  assert.ok(node.textContent.includes("Nothing here"));
  assert.ok(node.textContent.includes("Add something"));
  assert.ok(node.findButton("Add"));
});

test("navList renders items with a current marker", () => {
  const node = CW.navList({
    items: [{ id: "a", label: "A" }, { id: "b", label: "B" }],
    currentId: "b",
    onNavigate: () => {},
  });
  const items = node.findAll("app-nav__item");
  assert.equal(items.length, 2);
  const current = node.findAll("app-nav__item--current");
  assert.equal(current.length, 1);
  assert.equal(current[0].getAttribute("data-route"), "b");
});

test("bootstrap resolves shell nodes inside the supplied shadow root", async () => {
  const documentRoot = new Element("div");
  const decoyNav = new Element("div"); decoyNav.id = "app-nav";
  const decoyView = new Element("main"); decoyView.id = "view-root";
  const decoyTopbar = new Element("span"); decoyTopbar.id = "topbar-status";
  const decoyMode = new Element("p"); decoyMode.id = "app-mode";
  documentRoot.append(decoyNav, decoyView, decoyTopbar, decoyMode);
  documentStub._root = documentRoot;

  const host = new Element("controlel-panel");
  const shadowRoot = host.attachShadow({ mode: "open" });
  const navRoot = new Element("div"); navRoot.id = "app-nav";
  const viewRoot = new Element("main"); viewRoot.id = "view-root";
  const wizardRoot = new Element("div"); wizardRoot.id = "wizard-view";
  const draftStatus = new Element("div"); draftStatus.id = "draft-status";
  const stepper = new Element("nav"); stepper.id = "stepper";
  const stepPanel = new Element("section"); stepPanel.id = "step-panel";
  const wizardFooter = new Element("footer"); wizardFooter.id = "wizard-footer";
  wizardRoot.append(draftStatus, stepper, stepPanel, wizardFooter);
  const topbar = new Element("span"); topbar.id = "topbar-status";
  const modeRoot = new Element("p"); modeRoot.id = "app-mode";
  const shadowOnly = new Element("span"); shadowOnly.id = "shadow-only";
  shadowRoot.append(navRoot, viewRoot, wizardRoot, topbar, modeRoot, shadowOnly);
  documentRoot.append(host);

  assert.equal(documentStub.getElementById("shadow-only"), null, "document lookup does not cross the shadow root");
  assert.equal(shadowRoot.getElementById("shadow-only"), shadowOnly);

  const connection = fakeConnection({ responses: fullResponses() });
  const app = CA.bootstrap({
    root: shadowRoot,
    hass: { connection },
    panel: { config: { config_entry_id: "entry-shadow" } },
  });
  await settle(app);

  assert.ok(navRoot.findAll("app-nav__item").length > 0, "shadow-root navigation rendered");
  assert.ok(viewRoot.textContent.includes("Overview"), "shadow-root view rendered");
  assert.ok(app.setupWizard, "the setup write wizard is attached");
  assert.ok(stepPanel.textContent.includes("Current backend setup state"), "read-only readiness reaches wizard entry");
  assert.ok(stepPanel.textContent.includes("Not Ready"), "incomplete backend state guides the wizard entry");
  assert.equal(modeRoot.textContent, "Frontend API v1 · live");
  assert.equal(decoyNav.children.length, 0, "outer document navigation was untouched");
  assert.equal(decoyView.children.length, 0, "outer document view was untouched");
  assert.equal(decoyMode.textContent, "", "outer document mode label was untouched");
});
