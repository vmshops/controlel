/*
 * Controlel frontend — behavior tests (Node, no external dependencies).
 *
 * Run from the frontend/ directory:
 *   node --test tests/
 *
 * Covers:
 *   - navigation (route parsing, view switching, nav rendering)
 *   - module status rendering (all module states)
 *   - incomplete Heating → Continue setup
 *   - diagnostics level filtering (Basic / Detailed / Debug)
 *   - reusable component rendering
 *   - preserved wizard behavior (wizard.js unchanged)
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { Element, documentStub } = require("./dom-stub");

// The frontend scripts expect a `document` global; provide the stub first.
global.document = documentStub;

require("../mock-data.js");
require("../mock-app-data.js");
require("../components.js");
require("../app.js");

const CW = globalThis.CW;
const CA = globalThis.CA;
const DATA = globalThis.MOCK_APP_DATA;

/** Build an app shell on the stub DOM and return its parts. */
function buildApp() {
  const root = new Element("div");
  const navRoot = new Element("div"); navRoot.id = "app-nav";
  const viewRoot = new Element("main"); viewRoot.id = "view-root";
  const wizardRoot = new Element("div"); wizardRoot.id = "wizard-view";
  const topbar = new Element("span"); topbar.id = "topbar-status";
  root.append(navRoot, topbar, viewRoot, wizardRoot);
  documentStub._root = root;

  const app = CA.createApp({ data: DATA, navRoot, viewRoot, wizardRoot, topbarStatusRoot: topbar });
  return { app, root, navRoot, viewRoot, wizardRoot, topbar };
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

test("navigation renders the requested view and marks the current nav item", () => {
  const { app, navRoot, viewRoot, wizardRoot } = buildApp();

  app.navigate("modules");
  assert.ok(viewRoot.textContent.includes("Modules"));
  const current = navRoot.findAll("app-nav__item--current");
  assert.equal(current.length, 1);
  assert.equal(current[0].getAttribute("data-route"), "modules");
  assert.equal(current[0].getAttribute("aria-current"), "page");

  app.navigate("heating");
  assert.ok(viewRoot.textContent.includes("Heating"));
  assert.ok(viewRoot.textContent.includes("Current temperature"));
});

test("navigating to setup shows the wizard container and hides the view root", () => {
  const { app, viewRoot, wizardRoot } = buildApp();
  app.navigate("setup");
  assert.equal(viewRoot.hidden, true);
  assert.equal(wizardRoot.hidden, false);
  app.navigate("overview");
  assert.equal(viewRoot.hidden, false);
  assert.equal(wizardRoot.hidden, true);
});

test("unknown routes fall back to the default route", () => {
  const { app, viewRoot } = buildApp();
  app.navigate("does-not-exist");
  assert.equal(app.state.route, CA.DEFAULT_ROUTE);
  assert.ok(viewRoot.textContent.includes("Overview"));
});

test("clicking a navigation item navigates", () => {
  const { app, navRoot, viewRoot } = buildApp();
  const item = navRoot.findAll("app-nav__item").find((b) => b.getAttribute("data-route") === "diagnostics");
  assert.ok(item, "diagnostics nav item exists");
  item.dispatch("click");
  assert.equal(app.state.route, "diagnostics");
  assert.ok(viewRoot.textContent.includes("Diagnostics / Activity"));
});

test("topbar shows the overall status derived from modules", () => {
  const { topbar } = buildApp();
  // Heating is incomplete in the mock data → overall status is incomplete.
  assert.ok(topbar.textContent.includes("Incomplete setup"));
});

// ------------------------------------------------------- module status render

test("stateMeta maps every module state to a label and tone", () => {
  assert.deepEqual(CW.stateMeta("active"), { label: "Active", tone: "positive" });
  assert.deepEqual(CW.stateMeta("incomplete"), { label: "Incomplete setup", tone: "warning" });
  assert.deepEqual(CW.stateMeta("attention"), { label: "Needs attention", tone: "negative" });
  assert.deepEqual(CW.stateMeta("disabled"), { label: "Disabled", tone: "neutral" });
  assert.deepEqual(CW.stateMeta("not_configured"), { label: "Not configured", tone: "neutral" });
});

test("unknown states render neutrally instead of being guessed", () => {
  const meta = CW.stateMeta("something-new");
  assert.equal(meta.tone, "neutral");
  assert.equal(meta.label, "something-new");
});

test("moduleCard renders status, summary, warning count and actions", () => {
  const heating = DATA.modules.find((m) => m.id === "heating");
  const card = CW.moduleCard({ module: heating, onNavigate: () => {} });

  assert.ok(card.textContent.includes("Heating"));
  assert.ok(card.textContent.includes("Incomplete setup"));
  assert.ok(card.textContent.includes(heating.summary));
  assert.ok(card.textContent.includes("2 warnings"));
  assert.ok(card.findButton("Continue setup"), "primary action rendered");
  assert.ok(card.findButton("Open Heating"), "secondary action rendered");
});

test("modules view renders all four modules; only Heating is configured", () => {
  const { app, viewRoot } = buildApp();
  app.navigate("modules");

  const cards = viewRoot.findAll("module-card");
  assert.equal(cards.length, 4);

  const ids = cards.map((c) => c.getAttribute("data-module"));
  assert.deepEqual(ids, ["heating", "smart-charging", "lighting", "water-safety"]);

  const heating = cards.find((c) => c.getAttribute("data-module") === "heating");
  assert.ok(heating.textContent.includes("Incomplete setup"));

  for (const id of ["smart-charging", "lighting", "water-safety"]) {
    const card = cards.find((c) => c.getAttribute("data-module") === id);
    assert.ok(card.textContent.includes("Not configured"), `${id} marked not configured`);
    assert.equal(card.findButton("Continue setup"), null, `${id} has no setup action`);
  }
});

test("visibleItems hides hidden items and sorts by order", () => {
  const items = [
    { id: "b", order: 2 },
    { id: "a", order: 1 },
    { id: "x", order: 0, hidden: true },
  ];
  assert.deepEqual(CA.visibleItems(items).map((i) => i.id), ["a", "b"]);
});

test("overallStatus prefers attention, then incomplete, then active", () => {
  assert.equal(CA.overallStatus([{ state: "attention" }, { state: "active" }]), "attention");
  assert.equal(CA.overallStatus([{ state: "incomplete" }, { state: "active" }]), "incomplete");
  assert.equal(CA.overallStatus([{ state: "active" }]), "active");
  assert.equal(CA.overallStatus([{ state: "disabled" }]), "disabled");
  assert.equal(CA.overallStatus([]), "unknown");
});

// ------------------------------------------- incomplete heating → continue setup

test("modulePrimaryAction derives Continue setup for incomplete modules", () => {
  assert.deepEqual(CA.modulePrimaryAction({ state: "incomplete" }), { label: "Continue setup", route: "setup" });
  assert.deepEqual(CA.modulePrimaryAction({ state: "attention" }), { label: "Review issues", route: "diagnostics" });
  assert.equal(CA.modulePrimaryAction({ state: "not_configured" }), null);
});

test("overview offers Continue setup and it navigates to the wizard", () => {
  const { app, viewRoot, wizardRoot } = buildApp();
  const button = viewRoot.findButton("Continue setup");
  assert.ok(button, "Continue setup action present on overview");
  button.dispatch("click");
  assert.equal(app.state.route, "setup");
  assert.equal(wizardRoot.hidden, false);
});

test("heating module card primary action continues the existing setup", () => {
  const { app, viewRoot, wizardRoot } = buildApp();
  app.navigate("modules");
  const heatingCard = viewRoot.findAll("module-card").find((c) => c.getAttribute("data-module") === "heating");
  heatingCard.findButton("Continue setup").dispatch("click");
  assert.equal(app.state.route, "setup");
  assert.equal(wizardRoot.hidden, false);
});

test("heating view shows status, reason and completeness", () => {
  const { app, viewRoot } = buildApp();
  app.navigate("heating");

  assert.ok(viewRoot.textContent.includes("Living Room"));
  assert.ok(viewRoot.textContent.includes("21.4"));
  assert.ok(viewRoot.textContent.includes("21.0"));
  assert.ok(viewRoot.textContent.includes("No heating demand"));
  assert.ok(viewRoot.textContent.includes("SETUP_INCOMPLETE"));
  assert.ok(viewRoot.textContent.includes("3/5 complete"));
  assert.ok(viewRoot.textContent.includes("Sensor confirmation"));
  // Truthfulness: heat source is a permission state, not burner state.
  assert.ok(viewRoot.textContent.includes("permission"));
});

// ------------------------------------------------- diagnostics level filtering

test("filterEvents applies the selected maximum display level", () => {
  const events = DATA.activity;
  const basic = CA.filterEvents(events, "basic");
  const detailed = CA.filterEvents(events, "detailed");
  const debug = CA.filterEvents(events, "debug");

  assert.ok(basic.every((e) => e.level === "basic"));
  assert.ok(detailed.every((e) => e.level === "basic" || e.level === "detailed"));
  assert.equal(debug.length, events.length);
  assert.ok(basic.length < detailed.length);
  assert.ok(detailed.length < debug.length);
});

test("diagnostics view filters events by level and offers level buttons", () => {
  const { app, viewRoot } = buildApp();
  app.navigate("diagnostics");

  // Default level is basic.
  let rows = viewRoot.findAll("activity-row");
  assert.equal(rows.length, CA.filterEvents(DATA.activity, "basic").length);

  // Level buttons exist.
  assert.ok(viewRoot.findButton("Basic"));
  assert.ok(viewRoot.findButton("Detailed"));
  assert.ok(viewRoot.findButton("Debug"));

  // Switching to debug shows everything.
  viewRoot.findButton("Debug").dispatch("click");
  rows = viewRoot.findAll("activity-row");
  assert.equal(rows.length, DATA.activity.length);

  // Switching back to basic hides detailed/debug events.
  viewRoot.findButton("Basic").dispatch("click");
  rows = viewRoot.findAll("activity-row");
  assert.equal(rows.length, CA.filterEvents(DATA.activity, "basic").length);
});

test("activity row keeps reason codes and metadata behind expandable details", () => {
  const event = DATA.activity.find((e) => e.reasonCodes && e.reasonCodes.length > 0);
  let expanded = false;
  const row = CW.activityRow({ event, expanded, onToggle: () => { expanded = true; } });

  const details = row.findAll("activity-row__details")[0];
  assert.equal(details.hidden, true, "details hidden by default");
  assert.ok(row.findButton("Details"));

  // After toggling, the row re-renders with details visible.
  const rowOpen = CW.activityRow({ event, expanded: true, onToggle: () => {} });
  const detailsOpen = rowOpen.findAll("activity-row__details")[0];
  assert.equal(detailsOpen.hidden, false);
  assert.ok(detailsOpen.textContent.includes(event.reasonCodes[0]));
  assert.ok(detailsOpen.textContent.includes("Raw metadata"));
});

test("diagnostics shows an empty state when no events match the level", () => {
  const emptyData = { ...DATA, activity: [] };
  const { Element: E, documentStub: ds } = require("./dom-stub");
  const root = new E("div");
  const navRoot = new E("div"); navRoot.id = "app-nav";
  const viewRoot = new E("main"); viewRoot.id = "view-root";
  const wizardRoot = new E("div"); wizardRoot.id = "wizard-view";
  root.append(navRoot, viewRoot, wizardRoot);
  ds._root = root;

  const app = CA.createApp({ data: emptyData, navRoot, viewRoot, wizardRoot });
  app.navigate("diagnostics");
  assert.ok(viewRoot.textContent.includes("No events at this level"));
});

// ------------------------------------------------------- reusable components

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

test("settings view renders the settings overview rows", () => {
  const { app, viewRoot } = buildApp();
  app.navigate("settings");
  for (const label of ["Heating configuration", "Notifications", "Diagnostics level", "Language", "Advanced"]) {
    assert.ok(viewRoot.textContent.includes(label), `settings row present: ${label}`);
  }
  assert.ok(viewRoot.findButton("Continue setup"), "heating config row links to setup");
});

// ------------------------------------------------------- preserved wizard

test("wizard (preserved) renders steps, footer actions and incomplete status", () => {
  const root = new Element("div");
  const draftStatus = new Element("div"); draftStatus.id = "draft-status";
  const stepper = new Element("nav"); stepper.id = "stepper";
  const panel = new Element("section"); panel.id = "step-panel";
  const footer = new Element("footer"); footer.id = "wizard-footer";
  root.append(draftStatus, stepper, panel, footer);
  documentStub._root = root;

  // wizard.js reads window.CW / window.MOCK_SETUP_DATA.
  globalThis.window = globalThis;
  require("../wizard.js");

  // Stepper: 4 steps, step 1 current.
  assert.equal(stepper.findAll("stepper__step").length, 4);
  assert.equal(stepper.findAll("stepper__step--current").length, 1);

  // Step 1 content rendered.
  assert.ok(panel.textContent.includes("Home Assistant discovery summary"));

  // Footer: Save and finish later is always available; primary is Continue on step 1.
  assert.ok(footer.findButton("Save and finish later"), "Save and finish later available");
  assert.ok(footer.findButton("Continue"), "Continue available on step 1");
  assert.equal(footer.findButton("Activate"), null, "incomplete draft cannot activate");

  // Draft status shows incomplete with blocking count.
  assert.ok(draftStatus.textContent.includes("Incomplete"));
  assert.ok(draftStatus.textContent.includes("3 blocking"));
});

test("wizard: saving the draft keeps it incomplete (no activation)", () => {
  // The wizard already rendered in the previous test (same stub DOM).
  const footer = documentStub.getElementById("wizard-footer");
  const panel = documentStub.getElementById("step-panel");
  const draftStatus = documentStub.getElementById("draft-status");

  footer.findButton("Save and finish later").dispatch("click");
  assert.ok(draftStatus.textContent.includes("Saved"), "draft save time shown");
  assert.ok(draftStatus.textContent.includes("Incomplete"), "still incomplete after save");
  assert.equal(footer.findButton("Activate"), null, "still cannot activate");
  assert.ok(panel.textContent.length > 0, "panel still rendered");
});
