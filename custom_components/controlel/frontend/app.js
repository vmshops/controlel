/*
 * Controlel application shell — navigation, views and real Frontend API v1
 * data rendering.
 *
 * Responsibilities:
 *   - hash-based navigation between views (no backend calls);
 *   - rendering the Overview / Modules / Heating / Diagnostics / Settings /
 *     Setup views from the Frontend API v1 adapter (api-client.js) using the
 *     reusable CW components;
 *   - hosting the real setup-only wizard (wizard.js) as part of the "Setup"
 *     view without exposing activation or runtime control.
 *
 * Truthfulness (see AGENTS.md):
 *   - every view section shows an explicit state: loading / loaded / error;
 *   - unknown/null backend values render as "Unknown", never a guessed value;
 *   - heat-source permission, requested command, command outcome, reported
 *     state and physical state are shown as distinct fields;
 *   - a failed real request is NEVER silently replaced by mock data. Mock
 *     data is only used in an explicit demo mode.
 *
 * The pure logic (route parsing, event filtering, item visibility, state
 * mapping) is exported on global.CA so the behavior tests in tests/ can
 * exercise it without a browser.
 */
(function (global) {
  "use strict";

  const CW = global.CW;
  const { el, badge, statusBadge, pageHeader, section, metricCard, moduleCard, issuePanel, activityRow, emptyState, navList, noteBox, kvRow } = CW;

  // i18n (i18n.js): translated text is presentation only. Machine-facing
  // values (module ids, reason codes, API status codes, frontend_api_version)
  // are never translated.
  const CI18N = global.CI18N;
  const t = CI18N ? (key, params) => CI18N.t(key, params) : (key) => key;
  const has = CI18N ? (key) => CI18N.has(key) : () => false;

  // ------------------------------------------------------------- pure logic

  const ROUTES = ["overview", "modules", "heating", "diagnostics", "settings", "setup"];
  const DEFAULT_ROUTE = "overview";

  /**
   * Navigation items (data-driven; hidden/order are future-customization
   * hooks). `key` is the stable translation key; `label` is the canonical
   * English fallback.
   */
  const NAV_ITEMS = [
    { id: "overview", label: "Overview", key: "navigation.overview", order: 1, hidden: false },
    { id: "modules", label: "Modules", key: "navigation.modules", order: 2, hidden: false },
    { id: "heating", label: "Heating", key: "navigation.heating", order: 3, hidden: false },
    { id: "diagnostics", label: "Diagnostics", key: "navigation.diagnostics", order: 4, hidden: false },
    { id: "settings", label: "Settings", key: "navigation.settings", order: 5, hidden: false },
    { id: "setup", label: "Setup", key: "navigation.setup", order: 6, hidden: false },
  ];

  /** Parse a location hash ("#/heating", "#/heating?x=1") into a known route. */
  function parseRoute(hash) {
    if (!hash) return DEFAULT_ROUTE;
    const candidate = String(hash).replace(/^#\/?/, "").split(/[/?]/)[0];
    return ROUTES.includes(candidate) ? candidate : DEFAULT_ROUTE;
  }

  /** Diagnostics display levels, ordered from least to most detailed. */
  const DIAGNOSTICS_LEVELS = ["basic", "detailed", "debug"];

  function levelRank(level) {
    const i = DIAGNOSTICS_LEVELS.indexOf(level);
    return i === -1 ? -1 : i;
  }

  /**
   * Filter events by the selected maximum display level:
   * Basic → basic only; Detailed → basic + detailed; Debug → everything.
   */
  function filterEvents(events, maxLevel) {
    const max = levelRank(maxLevel);
    return (events || []).filter((e) => levelRank(e.level) <= max);
  }

  /**
   * Apply the future-customization contract to a list of items:
   * drop hidden items and sort by explicit order.
   */
  function visibleItems(items) {
    return (items || [])
      .filter((item) => !item.hidden)
      .slice()
      .sort((a, b) => (a.order || 0) - (b.order || 0));
  }

  // ------------------------------------------------- state vocabulary maps
  //
  // The backend uses its own explicit state strings. These maps render them
  // faithfully; anything not listed falls back to a neutral "Unknown"-style
  // badge rather than being guessed.

  // `key` is the stable translation key for the label; the state string
  // itself stays the machine-facing identity.
  const SYSTEM_STATUS_META = {
    active: { label: "Active", tone: "positive", key: "state.active" },
    degraded: { label: "Degraded", tone: "warning", key: "state.degraded" },
    stopped: { label: "Stopped", tone: "neutral", key: "state.stopped" },
  };

  const MODULE_STATUS_META = {
    active: { label: "Active", tone: "positive", key: "state.active" },
    inactive: { label: "Inactive", tone: "neutral", key: "state.inactive" },
    error: { label: "Error", tone: "negative", key: "state.error" },
  };

  const READINESS_META = {
    ready: { label: "Ready", tone: "positive", key: "state.ready" },
    incomplete: { label: "Incomplete", tone: "warning", key: "state.incomplete" },
    invalid: { label: "Invalid", tone: "negative", key: "state.invalid" },
    unknown: { label: "Unknown", tone: "neutral", key: "state.unknown" },
  };

  const DEMAND_META = {
    heat_required: { label: "Heating required", tone: "info", key: "state.heat_required" },
    no_heat_required: { label: "No heating demand", tone: "neutral", key: "state.no_heat_required" },
    indeterminate: { label: "Indeterminate", tone: "warning", key: "state.indeterminate" },
  };

  const MEASUREMENT_META = {
    fresh: { label: "Fresh", tone: "positive", key: "state.fresh" },
    expired: { label: "Expired", tone: "warning", key: "state.expired" },
    future_dated: { label: "Future-dated", tone: "warning", key: "state.future_dated" },
    missing: { label: "Missing", tone: "neutral", key: "state.missing" },
  };

  /**
   * {label, tone} for a state string (public contract; unknown states stay
   * neutral). The map entries also carry a translation `key`, which the
   * rendering helpers below resolve; `metaOf` itself stays key-free.
   */
  function metaOf(map, key) {
    if (key === null || key === undefined) return { label: "Unknown", tone: "neutral" };
    const m = map[key];
    if (!m) return { label: String(key), tone: "neutral" };
    return { label: m.label, tone: m.tone };
  }

  /** Translated label for a state; unknown states render their raw string. */
  function stateLabel(key, map) {
    if (key === null || key === undefined) return t("common.unknown");
    const m = map[key];
    if (!m) return String(key);
    return m.key && has(m.key) ? t(m.key) : m.label;
  }

  function stateBadge(map, key, labelOverride) {
    if (key === null || key === undefined) return badge(t("common.unknown"), "neutral");
    const m = map[key] || { label: String(key), tone: "neutral" };
    const label = labelOverride || (m.key && has(m.key) ? t(m.key) : m.label);
    return badge(label, m.tone);
  }

  function formatTime(value) {
    if (!value) return t("common.unknown");
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  }

  /** Map a real module ({module_id,status,reason}) to the moduleCard shape. */
  function toModuleCard(m) {
    const meta = metaOf(MODULE_STATUS_META, m.status);
    let primaryAction = null;
    if (m.status === "error") primaryAction = { label: t("action.review_issues"), route: "diagnostics" };
    else if (m.module_id === "heating") primaryAction = { label: t("action.open_heating"), route: "heating" };
    return {
      id: m.module_id,
      label: m.module_id,
      state: m.status,
      stateLabel: meta.label,
      summary: m.reason || t("module.no_reason"),
      warningCount: 0,
      updatedAt: null,
      primaryAction,
      secondaryAction: null,
      order: 0,
      hidden: false,
    };
  }

  /** Map a real operational event to the activityRow shape. */
  function toActivityEvent(e) {
    const codes = [];
    if (e.event_code) codes.push(e.event_code);
    if (e.reason_code) codes.push(e.reason_code);
    return {
      id: e.event_id,
      at: formatTime(e.timestamp),
      level: e.level || "basic",
      category: e.category,
      title: e.summary_code || e.event_code || e.category || t("common.event"),
      message: t("activity.reported_event"),
      reasonCodes: codes,
      metadata: {
        severity: e.severity,
        scope: e.scope,
        previous_state: e.previous_state,
        new_state: e.new_state,
        command: e.command,
      },
    };
  }

  // ------------------------------------------------------------------ views

  /**
   * Build the application shell.
   *
   * @param {object} opts
   * @param {string} opts.mode            "real" | "demo" | "unavailable"
   * @param {object} [opts.dataSource]    data source (null when unavailable)
   * @param {Function} [opts.demoFactory] () => data source, for enableDemo()
   * @param {object} opts.navRoot         element for the navigation list
   * @param {object} opts.viewRoot        element for the non-wizard views
   * @param {object} opts.wizardRoot      element hosting the wizard (wizard.js)
   * @param {object} [opts.topbarStatusRoot] element for the overall status badge
   * @param {object} [opts.modeRoot]         element for the connection-mode label
   * @param {object} [opts.renderRoot]       document/shadow root containing the shell
   * @param {Function} [opts.onSetupState]   reports read-only setup entry state to the wizard
   */
  function createApp({
    mode,
    dataSource,
    demoFactory,
    navRoot,
    viewRoot,
    wizardRoot,
    topbarStatusRoot,
    modeRoot,
    renderRoot,
    onSetupState,
  }) {
    const state = {
      route: DEFAULT_ROUTE,
      mode,
      dataSource: dataSource || null,
      diagnosticsLevel: "basic",
      expanded: new Set(),
      domains: {
        overview: freshDomain(),
        heating: freshDomain(),
        diagnostics: freshDomain(),
        setup: freshDomain(),
      },
    };

    function freshDomain() {
      return { status: "idle", data: null, error: null, inflight: null };
    }

    const api = {
      get state() { return state; },
      navigate(route) {
        const next = ROUTES.includes(route) ? route : DEFAULT_ROUTE;
        state.route = next;
        // Fresh data per view visit (read-only, event-driven). The setup
        // domain is kept cached because it drives the global topbar.
        for (const d of neededDomains(next)) {
          if (d !== "setup") state.domains[d] = freshDomain();
        }
        render();
      },
      setDiagnosticsLevel(level) {
        if (DIAGNOSTICS_LEVELS.includes(level)) {
          state.diagnosticsLevel = level;
          render();
        }
      },
      toggleEvent(id) {
        if (state.expanded.has(id)) state.expanded.delete(id);
        else state.expanded.add(id);
        render();
      },
      retryDomain(domain) {
        if (!state.domains[domain]) return;
        state.domains[domain] = freshDomain();
        loadDomain(domain);
      },
      setLanguage(pref) {
        if (CI18N && typeof CI18N.setLanguage === "function") CI18N.setLanguage(pref);
        render();
      },
      refresh() {
        for (const k of Object.keys(state.domains)) state.domains[k] = freshDomain();
        render();
      },
      enableDemo() {
        if (!demoFactory) return;
        state.mode = "demo";
        state.dataSource = demoFactory();
        for (const k of Object.keys(state.domains)) state.domains[k] = freshDomain();
        render();
      },
    };

    function neededDomains(route) {
      switch (route) {
        case "overview": return ["overview", "setup"];
        case "modules": return ["overview"];
        case "heating": return ["heating", "setup", "diagnostics"];
        case "diagnostics": return ["diagnostics"];
        case "settings": return ["setup"];
        case "setup": return ["setup"];
        default: return [];
      }
    }

    function loadDomain(domain) {
      if (!state.dataSource) return Promise.resolve();
      const d = state.domains[domain];
      if (d.inflight) return d.inflight;
      d.status = "loading";
      d.error = null;
      const p = state.dataSource[domain]().then(
        (result) => {
          if (result && result.status === "loaded") {
            d.status = "loaded";
            d.data = result.data;
          } else {
            d.status = "error";
            d.error = (result && result.error) || new Error(t("common.request_failed"));
          }
          d.inflight = null;
          render();
          return result;
        },
        (error) => {
          d.status = "error";
          d.error = error;
          d.inflight = null;
          render();
          return { status: "error", error };
        }
      );
      d.inflight = p;
      return p;
    }

    function render() {
      if (typeof onSetupState === "function") {
        const setup = state.domains.setup;
        onSetupState({
          status: setup.status,
          readiness: setup.status === "loaded" && setup.data ? setup.data.readiness : null,
          error: setup.error,
        });
      }
      if (navRoot) {
        navRoot.replaceChildren(navList({
          items: visibleItems(NAV_ITEMS).map((item) =>
            item.key && has(item.key) ? { ...item, label: t(item.key) } : item),
          currentId: state.route,
          onNavigate: (route) => api.navigate(route),
        }));
      }
      if (topbarStatusRoot) renderTopbar(topbarStatusRoot);
      renderModeLabel();
      // Re-translate the static shell markup (tagline, footer, labels) so a
      // language switch updates it too. No-op in Node (no querySelectorAll).
      if (CI18N && typeof CI18N.applyI18n === "function") {
        CI18N.applyI18n(renderRoot || document);
      }

      if (state.mode === "unavailable") {
        if (viewRoot) viewRoot.hidden = false;
        if (wizardRoot) wizardRoot.hidden = true;
        if (viewRoot) viewRoot.replaceChildren(renderUnavailable());
        return;
      }

      const isSetup = state.route === "setup";
      if (viewRoot) viewRoot.hidden = false;
      if (wizardRoot) wizardRoot.hidden = !isSetup;
      if (viewRoot) viewRoot.replaceChildren(renderView(state.route));

      for (const domain of neededDomains(state.route)) {
        if (state.domains[domain].status === "idle") loadDomain(domain);
      }
    }

    function renderModeLabel() {
      const target = modeRoot || _findById(renderRoot || document, "app-mode");
      if (!target) return;
      target.textContent =
        state.mode === "demo" ? t("mode.demo")
        : state.mode === "real" ? t("mode.real")
        : t("mode.disconnected");
    }

    function renderTopbar(root) {
      const setup = state.domains.setup;
      if (setup.status === "loaded" && setup.data && setup.data.readiness) {
        root.replaceChildren(stateBadge(READINESS_META, setup.data.readiness.state));
      } else if (setup.status === "error") {
        root.replaceChildren(badge(t("common.unavailable"), "warning"));
      } else {
        root.replaceChildren(badge(t("common.unknown"), "neutral"));
      }
    }

    function renderView(route) {
      switch (route) {
        case "overview": return renderOverview();
        case "modules": return renderModules();
        case "heating": return renderHeating();
        case "diagnostics": return renderDiagnostics();
        case "settings": return renderSettings();
        case "setup": return renderSetup();
        default: return null;
      }
    }

    // ------------------------------------------------------------- helpers

    function statePanel({ status, error, onRetry, loadingLabel, errorTitle }) {
      if (status === "loading" || status === "idle") {
        return el("div", { class: "state-panel state-panel--loading" },
          el("span", { class: "state-panel__icon" }, "…"),
          el("p", { class: "state-panel__message" }, loadingLabel || t("common.loading")));
      }
      if (status === "error") {
        return el("div", { class: "state-panel state-panel--error" },
          el("p", { class: "state-panel__title" }, errorTitle || t("common.unavailable")),
          el("p", { class: "state-panel__message" }, (error && error.message) || t("common.request_failed")),
          onRetry ? el("button", { class: "btn btn--secondary", onclick: onRetry }, t("common.retry")) : null
        );
      }
      return null;
    }

    function domainSection({ domain, title, lead, badges, actions, loaded, onRetry, loadingLabel, errorTitle }) {
      const st = state.domains[domain];
      const body = (st.status === "loaded" && st.data)
        ? loaded(st.data)
        : statePanel({ status: st.status, error: st.error, onRetry, loadingLabel, errorTitle });
      return section({ title, lead, badges, actions, children: body });
    }

    function readinessNeedsAction(setup) {
      return setup && setup.readiness &&
        (setup.readiness.state === "incomplete" || setup.readiness.state === "invalid");
    }

    function continueSetupButton() {
      return el("button", { class: "btn btn--primary", onclick: () => api.navigate("setup") }, t("action.continue_setup"));
    }

    // ------------------------------------------------------------- views

    function renderUnavailable() {
      return el("div", { class: "view" },
        pageHeader({
          title: t("navigation.overview"),
          subtitle: t("unavailable.subtitle"),
        }),
        el("div", { class: "state-panel state-panel--error" },
          el("p", { class: "state-panel__title" }, t("mode.disconnected")),
          el("p", { class: "state-panel__message" }, t("unavailable.message")),
          demoFactory
            ? el("button", { class: "btn btn--secondary", onclick: () => api.enableDemo() }, t("action.enable_demo"))
            : null
        ),
        noteBox(t("unavailable.note"), "info")
      );
    }

    function renderOverview() {
      const ov = state.domains.overview;
      const setup = state.domains.setup;

      const badges = [];
      if (ov.status === "loaded" && ov.data) badges.push(stateBadge(SYSTEM_STATUS_META, ov.data.system.status));

      const headerActions = [];
      if (setup.status === "loaded" && readinessNeedsAction(setup.data)) headerActions.push(continueSetupButton());

      const subtitle = (ov.status === "loaded" && ov.data && ov.data.generated_at)
        ? t("overview.subtitle_generated", { time: formatTime(ov.data.generated_at) })
        : t("overview.subtitle_api");

      return el("div", { class: "view" },
        pageHeader({ title: t("navigation.overview"), subtitle, badges, actions: headerActions }),

        domainSection({
          domain: "overview",
          title: t("section.modules"),
          lead: t("overview.modules_lead"),
          loaded: (data) => el("div", { class: "module-grid" },
            data.modules.length
              ? data.modules.map((m) => moduleCard({ module: toModuleCard(m), onNavigate: (route) => api.navigate(route) }))
              : emptyState({ title: t("empty.no_modules_title"), message: t("empty.no_modules_message") })
          ),
          onRetry: () => api.retryDomain("overview"),
        }),

        domainSection({
          domain: "overview",
          title: t("section.issues"),
          loaded: (data) => issuePanel({
            title: t("section.issues"),
            issues: data.attention.map((a) => ({ severity: a.severity, code: a.code, message: a.summary })),
            emptyMessage: t("common.no_issues"),
          }),
          onRetry: () => api.retryDomain("overview"),
        }),

        section({
          title: t("section.quick_actions"),
          children: el("div", { class: "quick-actions" },
            el("button", { class: "btn btn--secondary", onclick: () => api.navigate("heating") }, t("action.open_heating")),
            el("button", { class: "btn btn--secondary", onclick: () => api.navigate("diagnostics") }, t("action.open_diagnostics")),
            el("span", { class: "hint" }, t("overview.readonly_hint"))
          ),
        })
      );
    }

    function renderModules() {
      return el("div", { class: "view" },
        pageHeader({ title: t("navigation.modules"), subtitle: t("modules.subtitle") }),
        domainSection({
          domain: "overview",
          title: t("section.all_modules"),
          loaded: (data) => el("div", { class: "module-grid" },
            data.modules.length
              ? data.modules.map((m) => moduleCard({ module: toModuleCard(m), onNavigate: (route) => api.navigate(route) }))
              : emptyState({ title: t("empty.no_modules_title"), message: t("empty.no_modules_message") })
          ),
          onRetry: () => api.retryDomain("overview"),
        }),
        noteBox(t("modules.note"), "info")
      );
    }

    function renderHeatingCurrent(data) {
      const zones = data.zones || [];
      const hs = data.building && data.building.heat_source;

      const zoneBlocks = zones.map((z) => el("div", { class: "metric-group" },
        el("h4", { class: "metric-group__title" }, z.name),
        el("div", { class: "metric-grid" },
          metricCard({
            label: t("heating.current_temperature"),
            value: z.current_temperature_c === null ? t("common.unknown") : String(z.current_temperature_c),
            unit: "°C",
            sub: t("heating.measurement", { state: stateLabel(z.measurement_state, MEASUREMENT_META) }),
          }),
          metricCard({
            label: t("heating.target_temperature"),
            value: z.target_temperature_c === null ? t("common.unknown") : String(z.target_temperature_c),
            unit: "°C",
            sub: t("heating.target_sub"),
          }),
          metricCard({
            label: t("heating.demand"),
            value: stateLabel(z.demand_state, DEMAND_META),
            sub: z.demand_reason_code ? t("heating.reason", { code: z.demand_reason_code }) : t("heating.demand_sub"),
            tone: "info",
          })
        )
      ));

      const heatSource = el("div", { class: "metric-group" },
        el("h4", { class: "metric-group__title" }, t("heating.heat_source")),
        el("div", { class: "kv-grid" },
          kvRow(t("heating.permission"), hs ? hs.permission : t("common.unknown")),
          kvRow(t("heating.requested_command"), hs && hs.requested_command ? hs.requested_command : t("common.none")),
          kvRow(t("heating.command_outcome"), hs && hs.command_outcome ? hs.command_outcome : t("common.none")),
          kvRow(t("heating.reported_state"), hs && hs.reported_state ? hs.reported_state : t("common.unknown")),
          kvRow(t("heating.physical_state"), t("heating.physical_unknown"))
        ),
        noteBox(t("heating.distinct_note"), "neutral")
      );

      return el("div", { class: "heating-current" },
        zones.length ? zoneBlocks : emptyState({ title: t("empty.no_zones_title"), message: t("empty.no_zones_message") }),
        heatSource
      );
    }

    function renderHeating() {
      const setup = state.domains.setup;

      const badges = [];
      if (setup.status === "loaded" && setup.data) badges.push(stateBadge(READINESS_META, setup.data.readiness.state));

      const headerActions = [];
      if (setup.status === "loaded" && readinessNeedsAction(setup.data)) headerActions.push(continueSetupButton());

      return el("div", { class: "view" },
        pageHeader({
          title: t("navigation.heating"),
          subtitle: t("heating.subtitle"),
          badges,
          actions: headerActions,
        }),

        domainSection({
          domain: "heating",
          title: t("heating.current_state"),
          lead: t("heating.current_lead"),
          loaded: renderHeatingCurrent,
          onRetry: () => api.retryDomain("heating"),
        }),

        domainSection({
          domain: "setup",
          title: t("heating.status_reason"),
          loaded: (data) => {
            const r = data.readiness;
            return el("div", {},
              el("div", { class: "section__badges" },
                stateBadge(READINESS_META, r.state),
                r.reason_code ? badge(r.reason_code, "warning") : null
              ),
              noteBox(
                r.reason_code ? t("heating.readiness_reason", { code: r.reason_code }) : t("heating.no_readiness_reason"),
                r.state === "ready" ? "positive" : "warning"
              )
            );
          },
          onRetry: () => api.retryDomain("setup"),
        }),

        domainSection({
          domain: "setup",
          title: t("heating.completeness"),
          loaded: (data) => {
            const missing = data.missing_configuration || [];
            if (missing.length === 0) {
              return noteBox(t("setup.no_missing"), "positive");
            }
            return el("ul", { class: "completeness-list" },
              missing.map((m) => el("li", { class: "completeness-item" },
                el("span", { class: "completeness-item__label" }, m.code),
                badge(m.severity, m.severity === "error" ? "negative" : "warning")
              ))
            );
          },
          onRetry: () => api.retryDomain("setup"),
        }),

        domainSection({
          domain: "diagnostics",
          title: t("heating.recent_events"),
          actions: [el("button", { class: "btn btn--link", onclick: () => api.navigate("diagnostics") }, t("action.open_diagnostics"))],
          loaded: (data) => {
            const events = (data.recent_events || []).slice(0, 5).map(toActivityEvent);
            return events.length
              ? el("ul", { class: "activity-list" },
                  events.map((e) => activityRow({
                    event: e,
                    expanded: state.expanded.has(e.id),
                    onToggle: () => api.toggleEvent(e.id),
                  }))
                )
              : emptyState({ title: t("empty.no_events_title"), message: t("empty.no_events_message") });
          },
          onRetry: () => api.retryDomain("diagnostics"),
        }),

        noteBox(t("heating.readonly_note"), "neutral")
      );
    }

    function renderDiagnostics() {
      const level = state.diagnosticsLevel;

      const levelButtons = DIAGNOSTICS_LEVELS.map((l) => el("button", {
        class: `btn btn--sm ${l === level ? "btn--primary" : "btn--secondary"}`,
        "aria-pressed": l === level ? "true" : "false",
        onclick: () => api.setDiagnosticsLevel(l),
      }, t(`diagnostics.level_${l}`)));

      return el("div", { class: "view" },
        pageHeader({
          title: t("diagnostics.title"),
          subtitle: t("diagnostics.subtitle"),
        }),

        domainSection({
          domain: "diagnostics",
          title: t("diagnostics.health"),
          loaded: (data) => el("div", { class: "kv-grid" },
            kvRow(t("diagnostics.runtime_status"), data.health.runtime_status),
            kvRow(t("diagnostics.operating_mode"), data.health.operating_mode),
            kvRow(t("diagnostics.events_emitted"), String(data.health.event_stream.total_emitted)),
            kvRow(t("diagnostics.events_retained"), String(data.health.event_stream.retained)),
            kvRow(t("diagnostics.events_dropped"), String(data.health.event_stream.dropped))
          ),
          onRetry: () => api.retryDomain("diagnostics"),
        }),

        section({
          title: t("diagnostics.display_level"),
          lead: t("diagnostics.display_level_lead"),
          children: el("div", { class: "level-filter" }, levelButtons),
        }),

        domainSection({
          domain: "diagnostics",
          title: t("diagnostics.activity"),
          loaded: (data) => {
            const events = filterEvents((data.recent_events || []).map(toActivityEvent), level);
            return events.length
              ? el("ul", { class: "activity-list" },
                  events.map((e) => activityRow({
                    event: e,
                    expanded: state.expanded.has(e.id),
                    onToggle: () => api.toggleEvent(e.id),
                  }))
                )
              : emptyState({
                  title: t("empty.no_events_level_title"),
                  message: t("empty.no_events_level_message"),
                  action: el("button", { class: "btn btn--secondary", onclick: () => api.setDiagnosticsLevel("debug") }, t("action.show_debug")),
                });
          },
          onRetry: () => api.retryDomain("diagnostics"),
        }),

        domainSection({
          domain: "diagnostics",
          title: t("diagnostics.decision_trace"),
          loaded: (data) => {
            const trace = data.decision_trace;
            if (!trace) return noteBox(t("diagnostics.no_trace"), "neutral");
            return el("div", { class: "kv-grid" },
              kvRow(t("diagnostics.decision"), trace.decision_id),
              kvRow(t("diagnostics.zone"), trace.zone_id),
              kvRow(t("diagnostics.sensor"), trace.sensor_id),
              kvRow(t("diagnostics.action"), trace.action),
              kvRow(t("diagnostics.observed_at"), formatTime(trace.observed_at)),
              kvRow(t("diagnostics.reason"), trace.reason_code || "—"),
              kvRow(t("diagnostics.retained_total"), `${trace.retained_count} / ${trace.total_decisions}`)
            );
          },
          onRetry: () => api.retryDomain("diagnostics"),
        })
      );
    }

    function renderSettings() {
      const setup = state.domains.setup;
      const readiness = (setup.status === "loaded" && setup.data) ? setup.data.readiness : null;

      const rows = [
        {
          id: "heating-config",
          label: t("settings.heating_config"),
          description: t("settings.heating_config_desc"),
          state: readiness ? readiness.state : "unknown",
          action: { label: t("action.continue_setup"), route: "setup" },
          order: 1,
          hidden: false,
        },
        {
          id: "diagnostics",
          label: t("settings.diagnostics_level"),
          description: t("settings.diagnostics_level_desc"),
          state: "ok",
          action: { label: t("action.open_diagnostics"), route: "diagnostics" },
          order: 2,
          hidden: false,
        },
        {
          id: "notifications",
          label: t("settings.notifications"),
          description: t("settings.notifications_desc"),
          state: "not_configured",
          order: 3,
          hidden: false,
        },
        {
          id: "language",
          label: t("settings.language"),
          description: t("settings.language_desc"),
          state: "ok",
          order: 4,
          hidden: false,
        },
        {
          id: "advanced",
          label: t("settings.advanced"),
          description: t("settings.advanced_desc"),
          state: "not_configured",
          order: 5,
          hidden: false,
        },
      ];

      /**
       * Language preference control (frontend-local; persisted in
       * localStorage by the i18n layer, no backend involved).
       */
      function languageControl() {
        const i18n = CI18N ? CI18N.defaultI18n() : null;
        const preference = i18n ? i18n.preference : "auto";
        const select = el("select", {
          class: "select select--language",
          "aria-label": t("settings.language"),
          onchange: (e) => api.setLanguage((e.target && e.target.value) || "auto"),
        },
          el("option", { value: "auto", selected: preference === "auto" ? "" : null }, t("language.auto")),
          el("option", { value: "en", selected: preference === "en" ? "" : null }, t("language.en")),
          el("option", { value: "cs", selected: preference === "cs" ? "" : null }, t("language.cs"))
        );
        select.value = preference;
        return select;
      }

      const rendered = visibleItems(rows).map((s) => el("div", { class: "settings-row", "data-setting": s.id },
        el("div", { class: "settings-row__main" },
          el("div", { class: "settings-row__head" },
            el("span", { class: "settings-row__label" }, s.label),
            s.id === "language"
              ? badge(CI18N ? t(`language.${CI18N.language}`) : "English", "info")
              : statusBadge(s.state)
          ),
          el("p", { class: "settings-row__description" }, s.description)
        ),
        s.id === "language"
          ? languageControl()
          : s.action
            ? el("button", { class: "btn btn--secondary btn--sm", onclick: () => api.navigate(s.action.route) }, s.action.label)
            : el("span", { class: "hint" }, t("settings.placeholder"))
      ));

      return el("div", { class: "view" },
        pageHeader({
          title: t("navigation.settings"),
          subtitle: t("settings.subtitle"),
        }),
        section({ title: t("settings.overview"), children: el("div", { class: "settings-list" }, rendered) }),
        noteBox(t("settings.note"), "info")
      );
    }

    function renderSetup() {
      const setup = state.domains.setup;

      const badges = [];
      if (setup.status === "loaded" && setup.data) badges.push(stateBadge(READINESS_META, setup.data.readiness.state));

      return el("div", { class: "view" },
        pageHeader({
          title: t("setup.title"),
          subtitle: t("setup.subtitle"),
          badges,
        }),

        domainSection({
          domain: "setup",
          title: t("setup.readiness"),
          loaded: (data) => {
            const r = data.readiness;
            return el("div", {},
              el("div", { class: "section__badges" },
                stateBadge(READINESS_META, r.state),
                r.reason_code ? badge(r.reason_code, "warning") : null
              ),
              noteBox(
                r.state === "ready"
                  ? t("setup.ready")
                  : r.state === "incomplete"
                    ? t("setup.incomplete")
                    : r.state === "invalid"
                      ? t("setup.invalid")
                      : t("setup.unknown"),
                r.state === "ready" ? "positive" : r.state === "unknown" ? "neutral" : "warning"
              )
            );
          },
          onRetry: () => api.retryDomain("setup"),
        }),

        domainSection({
          domain: "setup",
          title: t("setup.missing_config"),
          loaded: (data) => {
            const missing = data.missing_configuration || [];
            if (missing.length === 0) return noteBox(t("setup.no_missing"), "positive");
            return el("ul", { class: "completeness-list" },
              missing.map((m) => el("li", { class: "completeness-item" },
                el("span", { class: "completeness-item__label" }, m.code),
                badge(m.severity, m.severity === "error" ? "negative" : "warning")
              ))
            );
          },
          onRetry: () => api.retryDomain("setup"),
        }),

        domainSection({
          domain: "setup",
          title: t("setup.validation"),
          loaded: (data) => {
            const messages = data.validation_messages || [];
            if (messages.length === 0) return noteBox(t("setup.no_validation"), "positive");
            return el("ul", { class: "issue-list" },
              messages.map((v) => el("li", { class: `issue issue--${v.severity === "error" ? "negative" : "warning"}` },
                badge(String(v.severity).toUpperCase(), v.severity === "error" ? "negative" : "warning"),
                el("span", { class: "issue__message" }, v.summary),
                el("code", { class: "issue__code" }, v.code)
              ))
            );
          },
          onRetry: () => api.retryDomain("setup"),
        }),

        noteBox(t("setup.readonly_note"), "info")
      );
    }

    render();
    return api;
  }

  // -------------------------------------------------------------- bootstrap

  // Re-entrant hash routing: the Home Assistant panel may (re)create the
  // shell on each connection, so the hashchange listener is added once and
  // always navigates the most recently created app. In the standalone page
  // and the Node test harness this behaves exactly as before.
  let _currentApp = null;
  let _hashListenerAdded = false;

  function _setupHashRouting(app) {
    _currentApp = app;
    if (global.location && "hash" in global.location) {
      app.navigate(parseRoute(global.location.hash));
    }
    if (!_hashListenerAdded && typeof global.addEventListener === "function") {
      _hashListenerAdded = true;
      global.addEventListener("hashchange", () => {
        if (_currentApp) _currentApp.navigate(parseRoute(global.location && global.location.hash));
      });
    }
  }

  function _findById(root, id) {
    if (!root) return null;
    if (typeof root.getElementById === "function") return root.getElementById(id);
    if (typeof root.querySelector === "function") return root.querySelector(`#${id}`);
    return null;
  }

  /** Bootstrap within a document or shadow root. */
  function bootstrap(options) {
    const CA_API = global.CA_API;
    if (!CA_API) return null;
    const opts = options && typeof options === "object" ? options : {};
    const root = opts.root || document;

    const hasLifecycleContext = Object.prototype.hasOwnProperty.call(opts, "hass") ||
      Object.prototype.hasOwnProperty.call(opts, "panel") ||
      Object.prototype.hasOwnProperty.call(opts, "config");
    const env = CA_API.detectHaEnvironment(
      global,
      hasLifecycleContext
        ? { hass: opts.hass, panel: opts.panel, panelConfig: opts.config }
        : null
    );
    let mode;
    let dataSource = null;
    let setupWriteClient = null;

    if (env.available) {
      mode = "real";
      try {
        const client = CA_API.createFrontendApiClient({ connection: env.connection, configEntryId: env.configEntryId });
        dataSource = CA_API.createRealDataSource(client);
        setupWriteClient = CA_API.createSetupWriteClient({ connection: env.connection, configEntryId: env.configEntryId });
      } catch (_err) {
        mode = "unavailable";
        dataSource = null;
      }
    } else {
      // No HA environment: real data is unavailable. Do NOT silently fall
      // back to mock data; offer an explicit demo mode instead.
      mode = "unavailable";
    }

    const setupWizard = setupWriteClient && global.CA_WIZARD && typeof global.CA_WIZARD.createSetupWizard === "function"
      ? global.CA_WIZARD.createSetupWizard({
          client: setupWriteClient,
          configEntryId: env.configEntryId,
          root,
          storage: global.localStorage || null,
        })
      : null;

    const app = createApp({
      mode,
      dataSource,
      demoFactory: global.MOCK_APP_DATA ? () => CA_API.createDemoDataSource(global.MOCK_APP_DATA) : null,
      navRoot: _findById(root, "app-nav"),
      viewRoot: _findById(root, "view-root"),
      wizardRoot: _findById(root, "wizard-view"),
      topbarStatusRoot: _findById(root, "topbar-status"),
      modeRoot: _findById(root, "app-mode"),
      renderRoot: root,
      onSetupState: setupWizard && typeof setupWizard.setEntryState === "function"
        ? (entryState) => setupWizard.setEntryState(entryState)
        : null,
    });

    if (setupWizard) app.setupWizard = setupWizard;

    // Hash routing: deep links + back/forward (re-entrant, see above).
    _setupHashRouting(app);
    return app;
  }

  // Browser only: the Node test harness calls createApp() directly.
  // In the Home Assistant panel, ha-panel.js sets CA_NO_AUTO_BOOTSTRAP and
  // calls CA.bootstrap() explicitly to match the element lifecycle.
  if (
    typeof window !== "undefined" &&
    window.document &&
    window.document.getElementById &&
    !window.CA_NO_AUTO_BOOTSTRAP
  ) {
    global.CONTROLEL_APP = bootstrap();
  }

  global.CA = {
    ROUTES,
    DEFAULT_ROUTE,
    NAV_ITEMS,
    DIAGNOSTICS_LEVELS,
    SYSTEM_STATUS_META,
    MODULE_STATUS_META,
    READINESS_META,
    DEMAND_META,
    MEASUREMENT_META,
    parseRoute,
    filterEvents,
    visibleItems,
    metaOf,
    toModuleCard,
    toActivityEvent,
    createApp,
    bootstrap,
  };
})(typeof window !== "undefined" ? window : globalThis);
