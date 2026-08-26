/*
 * Controlel — Home Assistant panel entrypoint (thin adapter).
 *
 * This module exposes the EXISTING Controlel application shell as a Home
 * Assistant custom element (`controlel-panel`). It does not reimplement the
 * shell: it builds the same DOM structure as index.html, forwards Home
 * Assistant's supported custom-panel properties to the shell, and loads the
 * existing scripts in their original order.
 *
 * Truthfulness / safety (see AGENTS.md):
 *   - Setup writes are limited to drafts and validation and use the existing
 *     authenticated Home Assistant WebSocket connection (`this.hass.connection`).
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
  // i18n.js first: components.js and app.js resolve their UI strings through
  // the shared CI18N instance it provides.
  "i18n.js",
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

/** Load the shell scripts exactly once, in their original order. */
function _ensureAssets() {
  if (!_assetsLoaded) {
    // The element lifecycle owns bootstrapping; stop app.js auto-bootstrapping.
    window.CA_NO_AUTO_BOOTSTRAP = true;
    _assetsLoaded = Promise.resolve()
      .then(() =>
        SCRIPTS.reduce(
          (chain, name) => chain.then(() => _loadScript(SCRIPT_BASE + name)),
          Promise.resolve()
        )
      )
      .catch((error) => {
        _assetsLoaded = null;
        throw error;
      });
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
        <p data-i18n="panel.readonly_footer">Setup drafts only · no activation or runtime control</p>
      </div>
    </aside>

    <div class="app__main">
      <header class="app__topbar">
        <span class="app__topbar-label" data-i18n="panel.overall_status">Overall status</span>
        <span id="topbar-status" class="app__topbar-status"></span>
      </header>

      <main id="view-root" class="app__content"></main>

      <div id="wizard-view" class="app__content app__content--wizard" hidden>
        <div id="draft-status" class="draft-status" hidden></div>
        <footer id="wizard-footer" class="wizard-footer"></footer>
        <nav id="stepper" class="stepper" aria-label="Setup steps"></nav>
        <section id="step-panel" class="step-panel" aria-live="polite"></section>
      </div>

    </div>
  `;
  return app;
}

class ControlelPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._panel = null;
    this._panelConfig = {};
    this._narrow = false;
    this._route = null;
    this._styleLink = null;
    this._styleLoaded = null;
    this._bootstrapped = false;
    this._connectionToken = 0;
  }

  /** Home Assistant's authenticated runtime object (official panel contract). */
  set hass(value) {
    const previousConnection = this._hass && this._hass.connection;
    this._hass = value || null;
    const nextConnection = this._hass && this._hass.connection;
    if (this._bootstrapped && previousConnection !== nextConnection) this._bootstrap();
  }

  get hass() {
    return this._hass;
  }

  /** Home Assistant panel metadata; integration config is `panel.config`. */
  set panel(value) {
    const previousEntryId = this._configEntryId();
    this._panel = value && typeof value === "object" ? value : null;
    if (this._bootstrapped && previousEntryId !== this._configEntryId()) this._bootstrap();
  }

  get panel() {
    return this._panel;
  }

  /** Backward-compatible standalone/test config property. */
  set config(value) {
    const previousEntryId = this._configEntryId();
    this._panelConfig = value && typeof value === "object" ? value : {};
    if (this._bootstrapped && previousEntryId !== this._configEntryId()) this._bootstrap();
  }

  get config() {
    return this._panelConfig;
  }

  set narrow(value) {
    this._narrow = Boolean(value);
    this.toggleAttribute("narrow", this._narrow);
  }

  get narrow() {
    return this._narrow;
  }

  set route(value) {
    this._route = value || null;
  }

  get route() {
    return this._route;
  }

  connectedCallback() {
    const token = ++this._connectionToken;
    Promise.all([_ensureAssets(), this._ensureStyle()])
      .then(() => {
        if (token !== this._connectionToken) return;
        this._bootstrap();
        this._bootstrapped = true;
      })
      .catch((err) => {
        if (token === this._connectionToken) this._renderError(err);
      });
  }

  disconnectedCallback() {
    // Invalidate pending work; reconnecting starts one fresh bootstrap.
    this._connectionToken += 1;
    this._bootstrapped = false;
  }

  _ensureStyle() {
    if (!this._styleLoaded) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = CSS_URL;
      this._styleLink = link;
      this._styleLoaded = new Promise((resolve, reject) => {
        link.onload = () => resolve();
        link.onerror = () => reject(new Error("Failed to load " + CSS_URL));
      }).catch((error) => {
        link.remove();
        if (this._styleLink === link) this._styleLink = null;
        this._styleLoaded = null;
        throw error;
      });
      this.shadowRoot.appendChild(link);
    }
    return this._styleLoaded;
  }

  _effectiveConfig() {
    const panelConfig = this._panel && this._panel.config;
    return panelConfig && typeof panelConfig === "object" ? panelConfig : this._panelConfig;
  }

  _configEntryId() {
    const config = this._effectiveConfig();
    return config && typeof config.config_entry_id === "string" ? config.config_entry_id : null;
  }

  _bootstrap() {
    const config = this._effectiveConfig();
    this.shadowRoot.replaceChildren(this._styleLink, _buildShellDOM());
    if (window.CA && typeof window.CA.bootstrap === "function") {
      window.CONTROLEL_APP = window.CA.bootstrap({
        root: this.shadowRoot,
        hass: this._hass,
        panel: this._panel,
        config,
        narrow: this._narrow,
        route: this._route,
      });
    }
  }

  _renderError(err) {
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
    const children = this._styleLink ? [this._styleLink, app] : [app];
    this.shadowRoot.replaceChildren(...children);
  }
}

if (!customElements.get("controlel-panel")) {
  customElements.define("controlel-panel", ControlelPanel);
}
