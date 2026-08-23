/*
 * Controlel application shell — navigation, views and real Frontend API v1
 * data rendering.
 *
 * Responsibilities:
 *   - hash-based navigation between views (no backend calls);
 *   - rendering the Overview / Modules / Heating / Diagnostics / Settings /
 *     Setup views from the Frontend API v1 adapter (api-client.js) using the
 *     reusable CW components;
 *   - hosting the existing setup wizard (wizard.js) as part of the "Setup"
 *     view, clearly labeled as a prototype/demo flow.
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

  // ------------------------------------------------------------- pure logic

  const ROUTES = ["overview", "modules", "heating", "diagnostics", "settings", "setup"];
  const DEFAULT_ROUTE = "overview";

  /** Navigation items (data-driven; hidden/order are future-customization hooks). */
  const NAV_ITEMS = [
    { id: "overview", label: "Overview", order: 1, hidden: false },
    { id: "modules", label: "Modules", order: 2, hidden: false },
    { id: "heating", label: "Heating", order: 3, hidden: false },
    { id: "diagnostics", label: "Diagnostics", order: 4, hidden: false },
    { id: "settings", label: "Settings", order: 5, hidden: false },
    { id: "setup", label: "Setup", order: 6, hidden: false },
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

  const SYSTEM_STATUS_META = {
    active: { label: "Active", tone: "positive" },
    degraded: { label: "Degraded", tone: "warning" },
    stopped: { label: "Stopped", tone: "neutral" },
  };

  const MODULE_STATUS_META = {
    active: { label: "Active", tone: "positive" },
    inactive: { label: "Inactive", tone: "neutral" },
    error: { label: "Error", tone: "negative" },
  };

  const READINESS_META = {
    ready: { label: "Ready", tone: "positive" },
    incomplete: { label: "Incomplete", tone: "warning" },
    invalid: { label: "Invalid", tone: "negative" },
    unknown: { label: "Unknown", tone: "neutral" },
  };

  const DEMAND_META = {
    heat_required: { label: "Heating required", tone: "info" },
    no_heat_required: { label: "No heating demand", tone: "neutral" },
    indeterminate: { label: "Indeterminate", tone: "warning" },
  };

  const MEASUREMENT_META = {
    fresh: { label: "Fresh", tone: "positive" },
    expired: { label: "Expired", tone: "warning" },
    future_dated: { label: "Future-dated", tone: "warning" },
    missing: { label: "Missing", tone: "neutral" },
  };

  function metaOf(map, key) {
    if (key === null || key === undefined) return { label: "Unknown", tone: "neutral" };
    return map[key] || { label: String(key), tone: "neutral" };
  }

  function stateBadge(map, key, labelOverride) {
    const m = metaOf(map, key);
    return badge(labelOverride || m.label, m.tone);
  }

  function formatTime(value) {
    if (!value) return "Unknown";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  }

  /** Map a real module ({module_id,status,reason}) to the moduleCard shape. */
  function toModuleCard(m) {
    const meta = metaOf(MODULE_STATUS_META, m.status);
    let primaryAction = null;
    if (m.status === "error") primaryAction = { label: "Review issues", route: "diagnostics" };
    else if (m.module_id === "heating") primaryAction = { label: "Open Heating", route: "heating" };
    return {
      id: m.module_id,
      label: m.module_id,
      state: m.status,
      stateLabel: meta.label,
      summary: m.reason || "No reason reported.",
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
      title: e.summary_code || e.event_code || e.category || "event",
      message: "Reported operational event (read-only).",
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
   */
  function createApp({ mode, dataSource, demoFactory, navRoot, viewRoot, wizardRoot, topbarStatusRoot }) {
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
            d.error = (result && result.error) || new Error("The request failed");
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
      if (navRoot) {
        navRoot.replaceChildren(navList({
          items: visibleItems(NAV_ITEMS),
          currentId: state.route,
          onNavigate: (route) => api.navigate(route),
        }));
      }
      if (topbarStatusRoot) renderTopbar(topbarStatusRoot);
      renderModeLabel();

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
      const modeEl = (typeof document !== "undefined" && document.getElementById) ? document.getElementById("app-mode") : null;
      if (!modeEl) return;
      modeEl.textContent =
        state.mode === "demo" ? "Demo mode · mock data"
        : state.mode === "real" ? "Frontend API v1 · live"
        : "Disconnected";
    }

    function renderTopbar(root) {
      const setup = state.domains.setup;
      if (setup.status === "loaded" && setup.data && setup.data.readiness) {
        root.replaceChildren(stateBadge(READINESS_META, setup.data.readiness.state));
      } else if (setup.status === "error") {
        root.replaceChildren(badge("Unavailable", "warning"));
      } else {
        root.replaceChildren(badge("Unknown", "neutral"));
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
          el("p", { class: "state-panel__message" }, loadingLabel || "Loading…"));
      }
      if (status === "error") {
        return el("div", { class: "state-panel state-panel--error" },
          el("p", { class: "state-panel__title" }, errorTitle || "Unavailable"),
          el("p", { class: "state-panel__message" }, (error && error.message) || "The request failed."),
          onRetry ? el("button", { class: "btn btn--secondary", onclick: onRetry }, "Retry") : null
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
      return el("button", { class: "btn btn--primary", onclick: () => api.navigate("setup") }, "Continue setup");
    }

    // ------------------------------------------------------------- views

    function renderUnavailable() {
      return el("div", { class: "view" },
        pageHeader({
          title: "Overview",
          subtitle: "Controlel is not connected to a Home Assistant Frontend API v1 source.",
        }),
        el("div", { class: "state-panel state-panel--error" },
          el("p", { class: "state-panel__title" }, "Disconnected"),
          el("p", { class: "state-panel__message" },
            "No authenticated Home Assistant connection or Controlel config entry was found in this environment. " +
            "Real data is unavailable and will not be replaced by mock values."),
          demoFactory
            ? el("button", { class: "btn btn--secondary", onclick: () => api.enableDemo() }, "Enable demo mode (mock data)")
            : null
        ),
        noteBox(
          "In a Home Assistant panel the shell uses the existing authenticated WebSocket connection and the " +
          "controlel/frontend_api/v1/* read-only commands. No custom authentication or transport is created here.",
          "info"
        )
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
        ? `Frontend API v1 · generated ${formatTime(ov.data.generated_at)}`
        : "Frontend API v1";

      return el("div", { class: "view" },
        pageHeader({ title: "Overview", subtitle, badges, actions: headerActions }),

        domainSection({
          domain: "overview",
          title: "Modules",
          lead: "Configured Controlel modules and their current state.",
          loaded: (data) => el("div", { class: "module-grid" },
            data.modules.length
              ? data.modules.map((m) => moduleCard({ module: toModuleCard(m), onNavigate: (route) => api.navigate(route) }))
              : emptyState({ title: "No modules reported", message: "The backend reported no modules." })
          ),
          onRetry: () => api.retryDomain("overview"),
        }),

        domainSection({
          domain: "overview",
          title: "Important warnings & issues",
          loaded: (data) => issuePanel({
            title: "Important warnings & issues",
            issues: data.attention.map((a) => ({ severity: a.severity, code: a.code, message: a.summary })),
            emptyMessage: "No important warnings or issues right now.",
          }),
          onRetry: () => api.retryDomain("overview"),
        }),

        section({
          title: "Quick actions",
          children: el("div", { class: "quick-actions" },
            el("button", { class: "btn btn--secondary", onclick: () => api.navigate("heating") }, "Open Heating"),
            el("button", { class: "btn btn--secondary", onclick: () => api.navigate("diagnostics") }, "Open Diagnostics"),
            el("span", { class: "hint" }, "Read-only: actions only navigate; no backend writes are made.")
          ),
        })
      );
    }

    function renderModules() {
      return el("div", { class: "view" },
        pageHeader({ title: "Modules", subtitle: "Each module is an independent capability." }),
        domainSection({
          domain: "overview",
          title: "All modules",
          loaded: (data) => el("div", { class: "module-grid" },
            data.modules.length
              ? data.modules.map((m) => moduleCard({ module: toModuleCard(m), onNavigate: (route) => api.navigate(route) }))
              : emptyState({ title: "No modules reported", message: "The backend reported no modules." })
          ),
          onRetry: () => api.retryDomain("overview"),
        }),
        noteBox("Only modules reported by the backend are shown. Modules that are not configured are not listed.", "info")
      );
    }

    function renderHeatingCurrent(data) {
      const zones = data.zones || [];
      const hs = data.building && data.building.heat_source;

      const zoneBlocks = zones.map((z) => el("div", { class: "metric-group" },
        el("h4", { class: "metric-group__title" }, z.name),
        el("div", { class: "metric-grid" },
          metricCard({
            label: "Current temperature",
            value: z.current_temperature_c === null ? "Unknown" : String(z.current_temperature_c),
            unit: "°C",
            sub: `Measurement: ${metaOf(MEASUREMENT_META, z.measurement_state).label}`,
          }),
          metricCard({
            label: "Target temperature",
            value: z.target_temperature_c === null ? "Unknown" : String(z.target_temperature_c),
            unit: "°C",
            sub: "Comfort target for the zone",
          }),
          metricCard({
            label: "Heating demand",
            value: metaOf(DEMAND_META, z.demand_state).label,
            sub: z.demand_reason_code ? `Reason: ${z.demand_reason_code}` : "Assessment from reported evidence",
            tone: "info",
          })
        )
      ));

      const heatSource = el("div", { class: "metric-group" },
        el("h4", { class: "metric-group__title" }, "Heat source"),
        el("div", { class: "kv-grid" },
          kvRow("Permission", hs ? hs.permission : "Unknown"),
          kvRow("Requested command", hs && hs.requested_command ? hs.requested_command : "None"),
          kvRow("Command outcome", hs && hs.command_outcome ? hs.command_outcome : "None"),
          kvRow("Reported state", hs && hs.reported_state ? hs.reported_state : "Unknown"),
          kvRow("Physical state", "Unknown (not reported)")
        ),
        noteBox(
          "Permission, requested command, command outcome and reported state are distinct. None of them is physical " +
          "confirmation that the burner is running; the physical state is reported as unknown.",
          "neutral"
        )
      );

      return el("div", { class: "heating-current" },
        zones.length ? zoneBlocks : emptyState({ title: "No zones reported", message: "The backend reported no zones." }),
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
          title: "Heating",
          subtitle: "Zone demand, heat source permission and reported state.",
          badges,
          actions: headerActions,
        }),

        domainSection({
          domain: "heating",
          title: "Current state",
          lead: "Values are reports and assessments from the backend — not physical confirmation.",
          loaded: renderHeatingCurrent,
          onRetry: () => api.retryDomain("heating"),
        }),

        domainSection({
          domain: "setup",
          title: "Status & reason",
          loaded: (data) => {
            const r = data.readiness;
            return el("div", {},
              el("div", { class: "section__badges" },
                stateBadge(READINESS_META, r.state),
                r.reason_code ? badge(r.reason_code, "warning") : null
              ),
              noteBox(
                r.reason_code ? `Readiness reason: ${r.reason_code}` : "No readiness reason reported.",
                r.state === "ready" ? "positive" : "warning"
              )
            );
          },
          onRetry: () => api.retryDomain("setup"),
        }),

        domainSection({
          domain: "setup",
          title: "Configuration completeness",
          loaded: (data) => {
            const missing = data.missing_configuration || [];
            if (missing.length === 0) {
              return noteBox("No missing configuration reported.", "positive");
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
          title: "Recent operational events",
          actions: [el("button", { class: "btn btn--link", onclick: () => api.navigate("diagnostics") }, "Open Diagnostics")],
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
              : emptyState({ title: "No recent events", message: "Operational events will appear here." });
          },
          onRetry: () => api.retryDomain("diagnostics"),
        }),

        noteBox(
          "A successful command is not physical confirmation, and a heat source permission is not burner state. " +
          "This view is read-only and performs no control logic.",
          "neutral"
        )
      );
    }

    function renderDiagnostics() {
      const level = state.diagnosticsLevel;

      const levelButtons = DIAGNOSTICS_LEVELS.map((l) => el("button", {
        class: `btn btn--sm ${l === level ? "btn--primary" : "btn--secondary"}`,
        "aria-pressed": l === level ? "true" : "false",
        onclick: () => api.setDiagnosticsLevel(l),
      }, l.charAt(0).toUpperCase() + l.slice(1)));

      return el("div", { class: "view" },
        pageHeader({
          title: "Diagnostics / Activity",
          subtitle: "Health, a readable activity list, and the latest decision trace.",
        }),

        domainSection({
          domain: "diagnostics",
          title: "Health",
          loaded: (data) => el("div", { class: "kv-grid" },
            kvRow("Runtime status", data.health.runtime_status),
            kvRow("Operating mode", data.health.operating_mode),
            kvRow("Events emitted", String(data.health.event_stream.total_emitted)),
            kvRow("Events retained", String(data.health.event_stream.retained)),
            kvRow("Events dropped", String(data.health.event_stream.dropped))
          ),
          onRetry: () => api.retryDomain("diagnostics"),
        }),

        section({
          title: "Display level",
          lead: "Basic shows essential events; Detailed adds warnings; Debug adds critical detail.",
          children: el("div", { class: "level-filter" }, levelButtons),
        }),

        domainSection({
          domain: "diagnostics",
          title: "Activity",
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
                  title: "No events at this level",
                  message: "Try a higher display level to see more detail.",
                  action: el("button", { class: "btn btn--secondary", onclick: () => api.setDiagnosticsLevel("debug") }, "Show Debug"),
                });
          },
          onRetry: () => api.retryDomain("diagnostics"),
        }),

        domainSection({
          domain: "diagnostics",
          title: "Latest decision trace",
          loaded: (data) => {
            const t = data.decision_trace;
            if (!t) return noteBox("No decision trace reported.", "neutral");
            return el("div", { class: "kv-grid" },
              kvRow("Decision", t.decision_id),
              kvRow("Zone", t.zone_id),
              kvRow("Sensor", t.sensor_id),
              kvRow("Action", t.action),
              kvRow("Observed at", formatTime(t.observed_at)),
              kvRow("Reason", t.reason_code || "—"),
              kvRow("Retained / total", `${t.retained_count} / ${t.total_decisions}`)
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
          label: "Heating configuration",
          description: "Zone, sensor and heat source bindings for the heating module.",
          state: readiness ? readiness.state : "unknown",
          action: { label: "Continue setup", route: "setup" },
          order: 1,
          hidden: false,
        },
        {
          id: "diagnostics",
          label: "Diagnostics level",
          description: "Basic, Detailed or Debug display level for the activity view.",
          state: "ok",
          action: { label: "Open Diagnostics", route: "diagnostics" },
          order: 2,
          hidden: false,
        },
        {
          id: "notifications",
          label: "Notifications",
          description: "Choose which Controlel events are surfaced (placeholder).",
          state: "not_configured",
          order: 3,
          hidden: false,
        },
        {
          id: "language",
          label: "Language",
          description: "Interface language (placeholder — English only in this prototype).",
          state: "not_configured",
          order: 4,
          hidden: false,
        },
        {
          id: "advanced",
          label: "Advanced",
          description: "Advanced options and prototype diagnostics (placeholder).",
          state: "not_configured",
          order: 5,
          hidden: false,
        },
      ];

      const rendered = visibleItems(rows).map((s) => el("div", { class: "settings-row", "data-setting": s.id },
        el("div", { class: "settings-row__main" },
          el("div", { class: "settings-row__head" },
            el("span", { class: "settings-row__label" }, s.label),
            statusBadge(s.state)
          ),
          el("p", { class: "settings-row__description" }, s.description)
        ),
        s.action
          ? el("button", { class: "btn btn--secondary btn--sm", onclick: () => api.navigate(s.action.route) }, s.action.label)
          : el("span", { class: "hint" }, "Placeholder")
      ));

      return el("div", { class: "view" },
        pageHeader({
          title: "Settings",
          subtitle: "Navigation and structure only — this shell does not implement settings writes.",
        }),
        section({ title: "Settings overview", children: el("div", { class: "settings-list" }, rendered) }),
        noteBox(
          "The Heating configuration row reflects the real setup readiness state. Other rows are placeholders; " +
          "no configuration is written by this shell.",
          "info"
        )
      );
    }

    function renderSetup() {
      const setup = state.domains.setup;

      const badges = [];
      if (setup.status === "loaded" && setup.data) badges.push(stateBadge(READINESS_META, setup.data.readiness.state));

      return el("div", { class: "view" },
        pageHeader({
          title: "Setup / Readiness",
          subtitle: "Real setup readiness, missing configuration and validation from Frontend API v1.",
          badges,
        }),

        domainSection({
          domain: "setup",
          title: "Readiness",
          loaded: (data) => {
            const r = data.readiness;
            return el("div", {},
              el("div", { class: "section__badges" },
                stateBadge(READINESS_META, r.state),
                r.reason_code ? badge(r.reason_code, "warning") : null
              ),
              noteBox(
                r.state === "ready"
                  ? "Setup is reported as ready."
                  : r.state === "incomplete"
                    ? "Setup is reported as incomplete. Resolve the items below before it can become active."
                    : r.state === "invalid"
                      ? "Setup is reported as invalid. Review the validation messages below."
                      : "Setup readiness is unknown.",
                r.state === "ready" ? "positive" : r.state === "unknown" ? "neutral" : "warning"
              )
            );
          },
          onRetry: () => api.retryDomain("setup"),
        }),

        domainSection({
          domain: "setup",
          title: "Missing configuration",
          loaded: (data) => {
            const missing = data.missing_configuration || [];
            if (missing.length === 0) return noteBox("No missing configuration reported.", "positive");
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
          title: "Validation messages",
          loaded: (data) => {
            const messages = data.validation_messages || [];
            if (messages.length === 0) return noteBox("No validation messages reported.", "positive");
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

        noteBox(
          "Setup is read-only here: this shell shows readiness and validation but does not mutate configuration or " +
          "activate. The prototype setup flow below uses demo data only.",
          "info"
        )
      );
    }

    render();
    return api;
  }

  // -------------------------------------------------------------- bootstrap

  function bootstrap() {
    const CA_API = global.CA_API;
    if (!CA_API) return null;

    const env = CA_API.detectHaEnvironment();
    let mode;
    let dataSource = null;

    if (env.available) {
      mode = "real";
      try {
        const client = CA_API.createFrontendApiClient({ connection: env.connection, configEntryId: env.configEntryId });
        dataSource = CA_API.createRealDataSource(client);
      } catch (_err) {
        mode = "unavailable";
        dataSource = null;
      }
    } else {
      // No HA environment: real data is unavailable. Do NOT silently fall
      // back to mock data; offer an explicit demo mode instead.
      mode = "unavailable";
    }

    const app = createApp({
      mode,
      dataSource,
      demoFactory: global.MOCK_APP_DATA ? () => CA_API.createDemoDataSource(global.MOCK_APP_DATA) : null,
      navRoot: document.getElementById("app-nav"),
      viewRoot: document.getElementById("view-root"),
      wizardRoot: document.getElementById("wizard-view"),
      topbarStatusRoot: document.getElementById("topbar-status"),
    });

    // Hash routing: deep links + back/forward.
    if (global.location && "hash" in global.location) {
      app.navigate(parseRoute(global.location.hash));
    }
    if (typeof global.addEventListener === "function") {
      global.addEventListener("hashchange", () => {
        app.navigate(parseRoute(global.location && global.location.hash));
      });
    }
    return app;
  }

  // Browser only: the Node test harness calls createApp() directly.
  if (typeof window !== "undefined" && window.document && window.document.getElementById) {
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
  };
})(typeof window !== "undefined" ? window : globalThis);
