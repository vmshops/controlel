/*
 * Controlel application shell — navigation, views and mock-data rendering.
 *
 * Responsibilities:
 *   - hash-based navigation between views (no backend calls);
 *   - rendering the Overview / Modules / Heating / Diagnostics / Settings
 *     views from MOCK_APP_DATA using the reusable CW components;
 *   - hosting the existing setup wizard (wizard.js) as the "Setup" view.
 *
 * The pure logic (route parsing, status derivation, event filtering, item
 * visibility) is exported on global.CA so the behavior tests in tests/ can
 * exercise it without a browser.
 *
 * Future UI customization: navigation items, modules and settings rows are
 * plain data objects with {id, label, order, hidden}. Rendering always goes
 * through visibleItems(), so hide/show, reorder and label overrides can be
 * added later without touching the view code. No layout schema yet.
 */
(function (global) {
  "use strict";

  const CW = global.CW;
  const { el, badge, statusBadge, pageHeader, section, metricCard, moduleCard, issuePanel, activityRow, emptyState, navList, noteBox } = CW;

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

  /**
   * Derive the overall app status from module states.
   * Explicit states win; nothing is inferred beyond the mapping.
   */
  function overallStatus(modules) {
    const visible = visibleItems(modules);
    if (visible.length === 0) return "unknown";
    if (visible.some((m) => m.state === "attention")) return "attention";
    if (visible.some((m) => m.state === "incomplete")) return "incomplete";
    if (visible.some((m) => m.state === "active")) return "active";
    return "disabled";
  }

  /**
   * Default primary action for a module state, used when the data layer does
   * not define one explicitly. Incomplete setup → Continue setup.
   */
  function modulePrimaryAction(module) {
    switch (module.state) {
      case "incomplete":
        return { label: "Continue setup", route: "setup" };
      case "attention":
        return { label: "Review issues", route: "diagnostics" };
      case "active":
      case "disabled":
        return { label: "Open module", route: module.route || "overview" };
      default:
        return null; // not_configured and unknown: no action is invented
    }
  }

  // ------------------------------------------------------------------ views

  function renderOverview(data, api) {
    const status = overallStatus(data.modules);
    const heating = data.modules.find((m) => m.id === "heating");
    const heatingIncomplete = heating && heating.state === "incomplete";

    const headerActions = [];
    if (heatingIncomplete) {
      headerActions.push(el("button", { class: "btn btn--primary", onclick: () => api.navigate("setup") }, "Continue setup"));
    }

    const moduleGrid = el("div", { class: "module-grid" },
      visibleItems(data.modules).map((m) => moduleCard({ module: m, onNavigate: (route) => api.navigate(route) }))
    );

    return el("div", { class: "view" },
      pageHeader({
        title: "Overview",
        subtitle: `${data.app.name} · ${data.app.provider} · ${data.app.version} · mock data only`,
        badges: [statusBadge(status)],
        actions: headerActions,
      }),

      section({
        title: "Modules",
        lead: "Configured Controlel modules and their current state.",
        children: moduleGrid,
      }),

      issuePanel({
        title: "Important warnings & issues",
        issues: data.issues,
        emptyMessage: "No important warnings or issues right now.",
      }),

      section({
        title: "Quick actions",
        children: el("div", { class: "quick-actions" },
          heatingIncomplete
            ? el("button", { class: "btn btn--primary", onclick: () => api.navigate("setup") }, "Continue setup")
            : null,
          el("button", { class: "btn btn--secondary", onclick: () => api.navigate("heating") }, "Open Heating"),
          el("button", { class: "btn btn--secondary", onclick: () => api.navigate("diagnostics") }, "Open Diagnostics"),
          el("span", { class: "hint" }, "Prototype: actions only navigate; no backend calls are made.")
        ),
      })
    );
  }

  function renderModules(data, api) {
    return el("div", { class: "view" },
      pageHeader({
        title: "Modules",
        subtitle: "Each module is an independent capability. Only Heating is configured in this prototype.",
      }),
      section({
        title: "All modules",
        children: el("div", { class: "module-grid" },
          visibleItems(data.modules).map((m) => moduleCard({ module: m, onNavigate: (route) => api.navigate(route) }))
        ),
      }),
      noteBox(
        "Modules marked “Not configured · coming later” are placeholders for the platform roadmap. " +
        "They expose no configuration and no control in this prototype.",
        "info"
      )
    );
  }

  function renderHeating(data, api) {
    const h = data.heating;
    const events = (h.recentEventIds || [])
      .map((id) => (data.activity || []).find((e) => e.id === id))
      .filter(Boolean);

    const headerActions = [];
    if (h.status.state === "incomplete") {
      headerActions.push(el("button", { class: "btn btn--primary", onclick: () => api.navigate("setup") }, "Continue setup"));
    }

    const completenessItems = el("ul", { class: "completeness-list" },
      h.completeness.items.map((item) => el("li", { class: `completeness-item completeness-item--${item.state}` },
        el("span", { class: "completeness-item__label" }, item.label),
        statusBadge(item.state)
      ))
    );

    return el("div", { class: "view" },
      pageHeader({
        title: "Heating",
        subtitle: `Zone: ${h.zone.name} (${h.zone.area})`,
        badges: [statusBadge(h.status.state, h.status.state === "incomplete" ? "Incomplete setup" : null)],
        actions: headerActions,
      }),

      section({
        title: "Current state",
        lead: "Values are reports and assessments from the (mock) data layer — not physical confirmation.",
        children: el("div", { class: "metric-grid" },
          metricCard({ label: "Current temperature", value: h.currentTemperature.value, unit: h.currentTemperature.unit, sub: h.currentTemperature.sub }),
          metricCard({ label: "Target temperature", value: h.targetTemperature.value, unit: h.targetTemperature.unit, sub: h.targetTemperature.sub }),
          metricCard({ label: "Heating demand", value: h.demand.label, sub: h.demand.sub, tone: "info" }),
          metricCard({ label: "Heat source", value: h.heatSource.label, sub: h.heatSource.sub, tone: "neutral" })
        ),
      }),

      section({
        title: "Status & reason",
        badges: [badge(h.status.reason, "warning")],
        children: noteBox(h.status.message, "warning"),
      }),

      section({
        title: "Configuration completeness",
        badges: [badge(`${h.completeness.configured}/${h.completeness.total} complete`, h.completeness.configured === h.completeness.total ? "positive" : "warning")],
        children: completenessItems,
      }),

      section({
        title: "Recent operational events",
        actions: [el("button", { class: "btn btn--link", onclick: () => api.navigate("diagnostics") }, "Open Diagnostics")],
        children: events.length
          ? el("ul", { class: "activity-list" },
              events.map((e) => activityRow({
                event: e,
                expanded: api.state.expanded.has(e.id),
                onToggle: () => api.toggleEvent(e.id),
              }))
            )
          : emptyState({ title: "No recent events", message: "Operational events will appear here." }),
      }),

      noteBox(
        "A successful command is not physical confirmation, and a heat source permission is not burner state. " +
        "This view is a mock overview — it performs no control logic.",
        "neutral"
      )
    );
  }

  function renderDiagnostics(data, api) {
    const level = api.state.diagnosticsLevel;
    const events = filterEvents(data.activity, level);

    const levelButtons = DIAGNOSTICS_LEVELS.map((l) => el("button", {
      class: `btn btn--sm ${l === level ? "btn--primary" : "btn--secondary"}`,
      "aria-pressed": l === level ? "true" : "false",
      onclick: () => api.setDiagnosticsLevel(l),
    }, l.charAt(0).toUpperCase() + l.slice(1)));

    return el("div", { class: "view" },
      pageHeader({
        title: "Diagnostics / Activity",
        subtitle: "A readable activity list. Technical reason codes and raw metadata are behind expandable Details.",
      }),

      section({
        title: "Display level",
        lead: "Basic shows essential events; Detailed adds assessments; Debug adds system-level detail.",
        children: el("div", { class: "level-filter" }, levelButtons),
      }),

      section({
        title: "Activity",
        badges: [badge(`${events.length} event${events.length === 1 ? "" : "s"}`, "neutral")],
        children: events.length
          ? el("ul", { class: "activity-list" },
              events.map((e) => activityRow({
                event: e,
                expanded: api.state.expanded.has(e.id),
                onToggle: () => api.toggleEvent(e.id),
              }))
            )
          : emptyState({
              title: "No events at this level",
              message: "Try a higher display level to see more detail.",
              action: el("button", { class: "btn btn--secondary", onclick: () => api.setDiagnosticsLevel("debug") }, "Show Debug"),
            }),
      })
    );
  }

  function renderSettings(data, api) {
    const rows = visibleItems(data.settings).map((s) => el("div", { class: "settings-row", "data-setting": s.id },
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
        subtitle: "Navigation and structure only — this prototype does not implement settings forms.",
      }),
      section({
        title: "Settings overview",
        children: el("div", { class: "settings-list" }, rows),
      }),
      noteBox(
        "Language and Advanced are placeholders. Real settings will be driven by the same module/data " +
        "structure so future customization (hide/show, reorder, rename) can be added without redesign.",
        "info"
      )
    );
  }

  function renderView(route, data, api) {
    switch (route) {
      case "overview": return renderOverview(data, api);
      case "modules": return renderModules(data, api);
      case "heating": return renderHeating(data, api);
      case "diagnostics": return renderDiagnostics(data, api);
      case "settings": return renderSettings(data, api);
      default: return null; // "setup" is rendered by wizard.js into its own container
    }
  }

  // ------------------------------------------------------------------- app

  /**
   * Build the application shell.
   *
   * @param {object} opts
   * @param {object} opts.data            MOCK_APP_DATA
   * @param {object} opts.navRoot         element for the navigation list
   * @param {object} opts.viewRoot        element for the non-wizard views
   * @param {object} opts.wizardRoot      element hosting the wizard (wizard.js)
   * @param {object} [opts.topbarStatusRoot] element for the overall status badge
   */
  function createApp({ data, navRoot, viewRoot, wizardRoot, topbarStatusRoot }) {
    const state = {
      route: DEFAULT_ROUTE,
      diagnosticsLevel: "basic",
      expanded: new Set(),
    };

    const api = {
      get state() { return state; },
      navigate(route) {
        state.route = ROUTES.includes(route) ? route : DEFAULT_ROUTE;
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
    };

    function render() {
      if (navRoot) {
        navRoot.replaceChildren(navList({
          items: visibleItems(NAV_ITEMS),
          currentId: state.route,
          onNavigate: (route) => api.navigate(route),
        }));
      }
      if (topbarStatusRoot) {
        topbarStatusRoot.replaceChildren(statusBadge(overallStatus(data.modules)));
      }

      const isWizard = state.route === "setup";
      if (viewRoot) viewRoot.hidden = isWizard;
      if (wizardRoot) wizardRoot.hidden = !isWizard;

      if (!isWizard && viewRoot) {
        viewRoot.replaceChildren(renderView(state.route, data, api));
      }
    }

    render();
    return api;
  }

  // -------------------------------------------------------------- bootstrap

  function bootstrap() {
    const data = global.MOCK_APP_DATA;
    if (!data) return null;

    const app = createApp({
      data,
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
    parseRoute,
    filterEvents,
    visibleItems,
    overallStatus,
    modulePrimaryAction,
    renderOverview,
    renderModules,
    renderHeating,
    renderDiagnostics,
    renderSettings,
    renderView,
    createApp,
  };
})(typeof window !== "undefined" ? window : globalThis);
