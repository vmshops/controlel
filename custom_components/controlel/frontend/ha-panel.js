/*
 * Controlel — Home Assistant panel entrypoint (thin adapter).
 *
 * This module exposes the EXISTING Controlel application shell as a Home
 * Assistant custom element (`controlel-panel`). It does not reimplement the
 * shell: it builds the same DOM structure as index.html, bridges the panel
 * config into `window.panelConfig` (the contract api-client.js already
 * reads), and loads the existing scripts in their original order.
 *
 * Truthfulness / safety (see AGENTS.md):
 *   - The shell stays read-only and uses the existing authenticated Home
 *     Assistant WebSocket connection (`window.hass.connection`).
 *   - No custom authentication, transport, or control actions are created.
 *   - If no config entry id is available, the shell renders its truthful
 *     "unavailable" state; it never falls back to mock data silently.
 *
 * The module is the `module_url` registered by the integration (see
 * custom_components/controlel/panel.py). It is a plain ES module so it can
 * be loaded by Home Assistant's custom-panel loader.
 */
"use strict";

const SCRIPT_BASE = "/controlel_static/";
const SCRIPTS = [
  // i18n.js first: components.js, wizard.js and app.js resolve their UI
  // strings through the shared CI18N instance it provides.
  "i18n.js",
  "mock-data.js",
  "mock-app-data.js",
  "api-client.js",
  "components.js",
  "wizard.js",
  "app.js",
];
const CSS_URL = SCRIPT_BASE + "styles.css";

let _assetsLoaded = null;

function _loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Failed to load " + src));
    document.head.appendChild(s);
  });
}

function _loadCss(href) {
  return new Promise((resolve, reject) => {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    l.onload = () => resolve();
    l.onerror = () => reject(new Error("Failed to load " + href));
    document.head.appendChild(l);
  });
}

/** Load the shell's CSS + scripts exactly once, in their original order. */
function _ensureAssets() {
  if (!_assetsLoaded) {
    // The element lifecycle owns bootstrapping; stop app.js auto-bootstrapping.
    window.CA_NO_AUTO_BOOTSTRAP = true;
    _assetsLoaded = Promise.resolve()
      .then(() => _loadCss(CSS_URL))
      .then(() =>
        SCRIPTS.reduce(
          (chain, name) => chain.then(() => _loadScript(SCRIPT_BASE + name)),
          Promise.resolve()
        )
      );
  }
  return _assetsLoaded;
}

/** Build the same shell DOM structure as index.html. */
function _buildShellDOM() {
  const app = document.createElement("div");
  app.id = "app";
  app.className = "app";
  // Static shell strings carry data-i18n keys; app.js re-translates them on
  // every render (CI18N.applyI18n), so a language switch updates the shell.
  app.innerHTML = `
    <aside class="app__sidebar">
      <div class="app__brand">
        <span class="app-logo" aria-hidden="true">C</span>
        <div>
          <h1 class="app__name">Controlel</h1>
          <p class="app__tagline" data-i18n="panel.tagline">Heating control platform</p>
        </div>
      </div>
      <div id="app-nav" class="app__nav"></div>
      <div class="app__sidebar-footer">
        <p id="app-mode" class="app__mode">Frontend API v1</p>
        <p data-i18n="panel.readonly_footer">Read-only · no configuration writes</p>
      </div>
    </aside>

    <div class="app__main">
      <header class="app__topbar">
        <span class="app__topbar-label" data-i18n="panel.overall_status">Overall status</span>
        <span id="topbar-status" class="app__topbar-status"></span>
      </header>

      <main id="view-root" class="app__content"></main>

      <!-- Setup view: the existing wizard renders into these containers (wizard.js). -->
      <div id="wizard-view" class="app__content app__content--wizard" hidden>
        <div class="note note--info" id="wizard-demo-label" data-i18n="panel.wizard_demo_label">
          Prototype setup flow (demo data only) — real setup readiness is shown above. Activation is not implemented.
        </div>
        <div id="draft-status" class="draft-status" hidden></div>
        <nav id="stepper" class="stepper" aria-label="Setup steps"></nav>
        <section id="step-panel" class="step-panel" aria-live="polite"></section>
        <footer id="wizard-footer" class="wizard-footer"></footer>
      </div>
    </div>
  `;
  return app;
}

class ControlelPanel extends HTMLElement {
  constructor() {
    super();
    this._panelConfig = {};
    this._bootstrapped = false;
  }

  /** Home Assistant sets `.config` before the element is connected. */
  set config(value) {
    this._panelConfig = value && typeof value === "object" ? value : {};
    if (this._bootstrapped) this._bootstrap();
  }

  get config() {
    return this._panelConfig;
  }

  connectedCallback() {
    _ensureAssets()
      .then(() => {
        this._bootstrap();
        this._bootstrapped = true;
      })
      .catch((err) => this._renderError(err));
  }

  _bootstrap() {
    // Bridge the panel config into the window for the shell's
    // detectHaEnvironment() (api-client.js reads window.panelConfig).
    window.panelConfig = {
      config_entry_id:
        (this._panelConfig && this._panelConfig.config_entry_id) || null,
    };
    // Build the shell DOM (same structure as index.html).
    this.innerHTML = "";
    this.appendChild(_buildShellDOM());
    // Bootstrap the app (re-entrant; app.js exports CA.bootstrap).
    if (window.CA && typeof window.CA.bootstrap === "function") {
      window.CONTROLEL_APP = window.CA.bootstrap();
    }
  }

  _renderError(err) {
    this.innerHTML = "";
    const app = document.createElement("div");
    app.className = "app";
    const message = (err && err.message) ? err.message : String(err);
    // Assets may have failed to load, so CI18N might be unavailable; the
    // English title is the canonical fallback.
    const title = (window.CI18N && typeof window.CI18N.t === "function")
      ? window.CI18N.t("panel.load_error")
      : "Controlel panel failed to load";
    app.innerHTML =
      '<div class="app__main"><main class="app__content">' +
      '<div class="state-panel state-panel--error">' +
      '<p class="state-panel__title"></p>' +
      '<p class="state-panel__message"></p>' +
      "</div></main></div>";
    app.querySelector(".state-panel__title").textContent = title;
    app.querySelector(".state-panel__message").textContent = message;
    this.appendChild(app);
  }
}

if (!customElements.get("controlel-panel")) {
  customElements.define("controlel-panel", ControlelPanel);
}
