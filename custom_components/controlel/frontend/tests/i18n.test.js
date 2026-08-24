/*
 * Controlel frontend — i18n layer behavior tests (Node, no deps).
 *
 * Run from the frontend/ directory:
 *   node --test tests/
 *
 * Covers:
 *   - catalog integrity (Czech covers the full English shell)
 *   - English canonical rendering and fallback
 *   - missing-key fallback (the UI can never render blank)
 *   - Auto language selection from the HA/frontend language
 *   - unsupported-language fallback to English
 *   - language preference switching and re-rendering
 *   - persistence of an explicit language preference
 *   - navigation/routing still works after a language switch
 *   - truthful Czech semantics: unknown stays unknown, permission is not
 *     burner state, disconnected never silently shows mock data
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { Element, documentStub } = require("./dom-stub");

// The frontend scripts expect a `document` global; provide the stub first.
global.document = documentStub;

require("../i18n.js");
require("../mock-data.js");
require("../mock-app-data.js");
require("../api-client.js");
require("../components.js");
require("../app.js");

const CI18N = globalThis.CI18N;
const CA = globalThis.CA;
const CA_API = globalThis.CA_API;
const DATA = globalThis.MOCK_APP_DATA;

// ------------------------------------------------------- catalog integrity

test("every English key has a Czech translation (full shell coverage)", () => {
  const enKeys = Object.keys(CI18N.CATALOGS.en);
  assert.ok(enKeys.length > 50, "English catalog is unexpectedly small");
  const missing = enKeys.filter(
    (key) => !Object.prototype.hasOwnProperty.call(CI18N.CATALOGS.cs, key)
  );
  assert.deepEqual(missing, [], "Czech catalog is missing: " + missing.join(", "));
});

test("English catalog values are non-empty strings", () => {
  for (const [key, value] of Object.entries(CI18N.CATALOGS.en)) {
    assert.equal(typeof value, "string", key);
    assert.ok(value.length > 0, key);
  }
});

test("machine-facing values are not translation keys", () => {
  // State strings, reason codes and ids must stay stable machine values.
  for (const key of Object.keys(CI18N.CATALOGS.en)) {
    assert.ok(!/^(ZONE_REQUIRED|SENSOR_CONFIRMATION_REQUIRED|ENABLED|DISABLED)$/.test(key), key);
  }
  assert.equal(CI18N.CATALOGS.en["state.active"], "Active");
});

// ------------------------------------------------------------- pure i18n

test("t() returns the English value for known keys", () => {
  const i18n = CI18N.createI18n({ preference: "en" });
  assert.equal(i18n.t("navigation.overview"), "Overview");
  assert.equal(i18n.t("common.unknown"), "Unknown");
  assert.equal(i18n.t("diagnostics.title"), "Diagnostics / Activity");
  assert.equal(i18n.t("setup.incomplete"), "Setup is reported as incomplete. Resolve the items below before it can become active.");
});

test("t() falls back to the key itself for a missing key (never blank)", () => {
  const i18n = CI18N.createI18n({ preference: "en" });
  assert.equal(i18n.t("no.such.key"), "no.such.key");
  assert.equal(i18n.has("no.such.key"), false);
  assert.equal(i18n.has("navigation.overview"), true);
});

test("auto preference uses the detected HA/frontend language", () => {
  const cs = CI18N.createI18n({ preference: "auto", detect: () => "cs-CZ" });
  assert.equal(cs.language, "cs");
  assert.equal(cs.t("navigation.overview"), "Přehled");

  const en = CI18N.createI18n({ preference: "auto", detect: () => "en-US" });
  assert.equal(en.language, "en");
  assert.equal(en.t("navigation.overview"), "Overview");
});

test("auto preference falls back to English for unsupported languages", () => {
  const de = CI18N.createI18n({ preference: "auto", detect: () => "de-DE" });
  assert.equal(de.language, "en");
  assert.equal(de.t("navigation.overview"), "Overview");

  const none = CI18N.createI18n({ preference: "auto" });
  assert.equal(none.language, "en");
});

test("an explicit preference wins over detection", () => {
  const i18n = CI18N.createI18n({ preference: "cs", detect: () => "en-US" });
  assert.equal(i18n.language, "cs");
  assert.equal(i18n.t("navigation.heating"), "Topení");
});

test("setLanguage switches the active language and re-resolves", () => {
  const i18n = CI18N.createI18n({ detect: () => "en-US" });
  assert.equal(i18n.language, "en");
  assert.equal(i18n.setLanguage("cs"), "cs");
  assert.equal(i18n.t("navigation.settings"), "Nastavení");
  assert.equal(i18n.setLanguage("auto"), "en");
  assert.equal(i18n.t("navigation.settings"), "Settings");
});

test("an invalid preference falls back to auto", () => {
  const i18n = CI18N.createI18n({ detect: () => "cs-CZ" });
  assert.equal(i18n.setLanguage("xx"), "cs"); // auto → detected cs
  assert.equal(i18n.preference, "auto");
});

test("placeholders are substituted, including language-aware plurals", () => {
  const en = CI18N.createI18n({ preference: "en" });
  assert.equal(en.t("module.warnings", { count: 3 }), "3 warnings");
  assert.equal(en.t("module.warnings", { count: 1 }), "1 warning");
  assert.ok(en.t("wizard.incomplete_note", { count: 1 }).includes("1 blocking item"));
  assert.ok(en.t("wizard.incomplete_note", { count: 2 }).includes("2 blocking items"));
  const cs = CI18N.createI18n({ preference: "cs" });
  assert.equal(cs.t("module.warnings", { count: 3 }), "3 varování");
  assert.equal(cs.t("module.warnings", { count: 1 }), "1 varování");
  assert.ok(cs.t("wizard.warnings_recorded", { count: 2 }).includes("2 varování"));
  // Czech has three plural forms: 1, 2–4, and 0/5+.
  assert.ok(cs.t("wizard.incomplete_note", { count: 1 }).includes("1 blokující položka"));
  assert.ok(cs.t("wizard.incomplete_note", { count: 3 }).includes("3 blokující položky"));
  assert.ok(cs.t("wizard.incomplete_note", { count: 5 }).includes("5 blokujících položek"));
  assert.ok(cs.t("wizard.incomplete_note", { count: 0 }).includes("0 blokujících položek"));
});

test("the explicit preference persists to storage and is re-read", () => {
  const store = {};
  const storage = {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
  };
  const first = CI18N.createI18n({ storage, detect: () => "en-US" });
  assert.equal(first.preference, "auto");
  first.setLanguage("cs");
  assert.equal(store[CI18N.STORAGE_KEY], "cs");

  const second = CI18N.createI18n({ storage, detect: () => "en-US" });
  assert.equal(second.preference, "cs");
  assert.equal(second.language, "cs");
  assert.equal(second.t("navigation.overview"), "Přehled");
});

test("a stored unsupported preference falls back to auto", () => {
  const storage = { getItem: () => "xx", setItem: () => {} };
  const i18n = CI18N.createI18n({ storage, detect: () => "cs-CZ" });
  assert.equal(i18n.preference, "auto");
  assert.equal(i18n.language, "cs");
});

// ------------------------------------------------------- app-level (shell)

function overviewRaw() {
  return {
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    system: { status: "active", operating_mode: "normal", operating_mode_reason: null, operating_mode_since: null },
    modules: [{ module_id: "heating", status: "active", reason: null }],
    attention: [],
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

function setupRaw() {
  return {
    frontend_api_version: 1,
    generated_at: "2026-08-22T10:00:00+02:00",
    readiness: { state: "incomplete", reason_code: "SETUP_INCOMPLETE" },
    missing_configuration: [{ code: "SENSOR_CONFIRMATION_REQUIRED", scope: { type: "zone" }, severity: "error" }],
    validation_messages: [],
  };
}

function fakeConnection(responses) {
  return {
    sendMessagePromise(message) {
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

function buildApp({ responses = {} } = {}) {
  const connection = fakeConnection(responses);
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
    mode: "real",
    dataSource,
    demoFactory: () => CA_API.createDemoDataSource(DATA),
    navRoot,
    viewRoot,
    wizardRoot,
    topbarStatusRoot: topbar,
  });
  return { app, navRoot, viewRoot, wizardRoot, topbar, modeEl };
}

async function settle(app) {
  const pending = Object.values(app.state.domains).map((d) => d.inflight).filter(Boolean);
  if (pending.length) await Promise.all(pending);
}

/** Run a test with the shared instance in a known language, then restore. */
async function withLanguage(language, fn) {
  CI18N.setLanguage(language);
  try {
    await fn();
  } finally {
    CI18N.setLanguage("en");
  }
}

test("the shell renders in English by default (canonical fallback)", async () => {
  await withLanguage("en", async () => {
    const { app, navRoot, viewRoot } = buildApp({
      responses: { overview: overviewRaw(), heating: heatingRaw(), setup: setupRaw() },
    });
    app.navigate("overview");
    await settle(app);
    assert.ok(viewRoot.textContent.includes("Overview"));
    assert.ok(viewRoot.textContent.includes("Modules"));
    assert.ok(navRoot.textContent.includes("Heating"));
    assert.ok(navRoot.textContent.includes("Diagnostics"));
    assert.ok(navRoot.textContent.includes("Settings"));
  });
});

test("the shell renders in Czech after setLanguage('cs')", async () => {
  await withLanguage("cs", async () => {
    const { app, navRoot, viewRoot } = buildApp({
      responses: { overview: overviewRaw(), heating: heatingRaw(), setup: setupRaw() },
    });
    app.navigate("overview");
    await settle(app);
    assert.ok(navRoot.textContent.includes("Přehled"), "nav overview");
    assert.ok(navRoot.textContent.includes("Moduly"), "nav modules");
    assert.ok(navRoot.textContent.includes("Topení"), "nav heating");
    assert.ok(navRoot.textContent.includes("Diagnostika"), "nav diagnostics");
    assert.ok(navRoot.textContent.includes("Nastavení"), "nav settings");
    assert.ok(viewRoot.textContent.includes("Přehled"), "view title");
    assert.ok(viewRoot.textContent.includes("Moduly"), "modules section");
    assert.ok(viewRoot.textContent.includes("Rychlé akce"), "quick actions");
  });
});

test("language preference switching re-renders the navigation", async () => {
  const { app, navRoot } = buildApp({
    responses: { overview: overviewRaw(), heating: heatingRaw(), setup: setupRaw() },
  });
  try {
    app.navigate("overview");
    await settle(app);
    assert.ok(navRoot.textContent.includes("Overview"), "starts in English");

    app.setLanguage("cs");
    assert.ok(navRoot.textContent.includes("Přehled"), "switches to Czech");
    assert.ok(!navRoot.textContent.includes("Overview"), "English nav label gone");

    app.setLanguage("en");
    assert.ok(navRoot.textContent.includes("Overview"), "switches back to English");
  } finally {
    CI18N.setLanguage("en");
  }
});

test("navigation and routing still work after a language switch", async () => {
  await withLanguage("cs", async () => {
    const { app, viewRoot } = buildApp({
      responses: { overview: overviewRaw(), heating: heatingRaw(), setup: setupRaw() },
    });
    app.navigate("heating");
    await settle(app);
    assert.equal(app.state.route, "heating");
    assert.ok(viewRoot.textContent.includes("Topení"), "Czech heating title");
    assert.ok(viewRoot.textContent.includes("Aktuální teplota"), "Czech temperature label");
    assert.ok(viewRoot.textContent.includes("21.4"), "value rendered");

    app.navigate("diagnostics");
    await settle(app);
    assert.equal(app.state.route, "diagnostics");
    assert.ok(viewRoot.textContent.includes("Diagnostika / Aktivita"), "Czech diagnostics title");
  });
});

test("Czech keeps the truthful heat-source semantics", async () => {
  await withLanguage("cs", async () => {
    const { app, viewRoot } = buildApp({
      responses: { overview: overviewRaw(), heating: heatingRaw(), setup: setupRaw() },
    });
    app.navigate("heating");
    await settle(app);
    const text = viewRoot.textContent;
    assert.ok(text.includes("Oprávnění"), "permission field");
    assert.ok(text.includes("disabled"), "permission value stays the machine value");
    assert.ok(text.includes("Požadovaný příkaz"), "requested command field");
    assert.ok(text.includes("Výsledek příkazu"), "command outcome field");
    assert.ok(text.includes("Hlášený stav"), "reported state field");
    assert.ok(text.includes("Fyzikální stav"), "physical state field");
    assert.ok(text.includes("Neznámý (nehlášen)"), "physical state stays unknown");
    assert.ok(text.includes("hořák"), "note explains permission is not burner state");
  });
});

test("unknown/null values render as 'Neznámé' in Czech", async () => {
  await withLanguage("cs", async () => {
    const { app, viewRoot } = buildApp({
      responses: {
        overview: overviewRaw(),
        setup: setupRaw(),
        heating: {
          ...heatingRaw(),
          zones: [{
            zone_id: "z", name: "Zóna", current_temperature_c: null, measurement_state: "missing",
            measurement_age_seconds: null, target_temperature_c: 21.0, demand_state: "indeterminate",
            demand_reason_code: null, last_decision: null,
          }],
        },
      },
    });
    app.navigate("heating");
    await settle(app);
    assert.ok(viewRoot.textContent.includes("Neznámé"), "null temperature shown as unknown");
    assert.ok(viewRoot.textContent.includes("Chybí"), "measurement state shown");
    assert.ok(viewRoot.textContent.includes("Nedostatečně určeno"), "indeterminate demand shown");
  });
});

test("a failed request in Czech surfaces the backend error (no mock fallback)", async () => {
  await withLanguage("cs", async () => {
    const { app, viewRoot } = buildApp({
      responses: { overview: { __error: "config entry is not loaded" } },
    });
    app.navigate("overview");
    await settle(app);
    assert.ok(viewRoot.textContent.includes("Nedostupné"), "Czech error state");
    assert.ok(viewRoot.textContent.includes("config entry is not loaded"), "backend error surfaced");
    assert.ok(viewRoot.findButton("Zkusit znovu"), "Czech retry action");
    assert.ok(!viewRoot.textContent.includes("Living Room"), "no mock data substituted");
  });
});

test("unavailable mode in Czech offers explicit demo and never shows mock data", async () => {
  await withLanguage("cs", async () => {
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

    assert.ok(vRoot.textContent.includes("Nepřipojeno"), "Czech disconnected state");
    assert.ok(vRoot.findButton("Zapnout demo režim (ukázková data)"), "explicit demo action");
    assert.ok(!vRoot.textContent.includes("Living Room"), "no mock data shown by default");
  });
});

test("settings shows the language row with Auto / English / Czech options", async () => {
  await withLanguage("en", async () => {
    const { app, viewRoot } = buildApp({
      responses: { overview: overviewRaw(), heating: heatingRaw(), setup: setupRaw() },
    });
    app.navigate("settings");
    await settle(app);
    assert.ok(viewRoot.textContent.includes("Language"), "language row label");
    assert.ok(viewRoot.textContent.includes("Auto"), "auto option");
    assert.ok(viewRoot.textContent.includes("English"), "english option");
    assert.ok(viewRoot.textContent.includes("Czech"), "czech option");
    const select = viewRoot.findAll("select--language")[0];
    assert.ok(select, "language select rendered");
  });
});

test("changing the language select switches the shell language", async () => {
  const { app, viewRoot, navRoot } = buildApp({
    responses: { overview: overviewRaw(), heating: heatingRaw(), setup: setupRaw() },
  });
  try {
    app.navigate("settings");
    await settle(app);
    const select = viewRoot.findAll("select--language")[0];
    assert.ok(select, "language select rendered");

    select.dispatch("change", { target: { value: "cs" } });
    assert.equal(CI18N.language, "cs", "preference applied");
    assert.ok(navRoot.textContent.includes("Přehled"), "nav re-rendered in Czech");

    select.dispatch("change", { target: { value: "en" } });
    assert.equal(CI18N.language, "en", "preference restored");
    assert.ok(navRoot.textContent.includes("Overview"), "nav re-rendered in English");
  } finally {
    CI18N.setLanguage("en");
  }
});

test("wizard renders in Czech with truthful binding semantics", async () => {
  await withLanguage("cs", async () => {
    const root = new Element("div");
    const draftStatus = new Element("div"); draftStatus.id = "draft-status";
    const stepper = new Element("nav"); stepper.id = "stepper";
    const panel = new Element("section"); panel.id = "step-panel";
    const footer = new Element("footer"); footer.id = "wizard-footer";
    root.append(draftStatus, stepper, panel, footer);
    documentStub._root = root;

    globalThis.window = globalThis;
    require("../wizard.js");

    assert.ok(panel.textContent.includes("Souhrn objevu v Home Assistant"), "Czech discovery title");
    assert.ok(footer.findButton("Uložit a dokončit později"), "Czech save-later action");
    assert.ok(footer.findButton("Pokračovat"), "Czech continue action");
    assert.ok(draftStatus.textContent.includes("Nekompletní"), "Czech incomplete status");
    assert.ok(draftStatus.textContent.includes("3 blokujících"), "Czech blocking count");
  });
});
