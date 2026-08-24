/*
 * Controlel — reusable UI components (vanilla JS, no build step).
 *
 * Components are small, stateless render helpers. They receive data + event
 * callbacks and return DOM nodes; all state lives in the owning view
 * (wizard.js for the setup wizard, app.js for the application shell).
 *
 * The global wrapper is Node-safe so the same components can be exercised by
 * the behavior tests in tests/ without a browser.
 */
(function (global) {
  "use strict";

  // i18n (i18n.js): translated text is presentation only. Machine-facing
  // values (state strings, codes, ids) are never translated.
  const CI18N = global.CI18N;
  const t = CI18N ? (key, params) => CI18N.t(key, params) : (key) => key;
  const has = CI18N ? (key) => CI18N.has(key) : () => false;

  /** Create a DOM element with attributes, event handlers and children. */
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined) continue;
        if (key === "class") node.className = value;
        else if (key === "checked" || key === "disabled" || key === "hidden") {
          if (value) node[key] = true;
        } else if (key.startsWith("on") && typeof value === "function") {
          node.addEventListener(key.slice(2), value);
        } else {
          node.setAttribute(key, value);
        }
      }
    }
    for (const child of children) {
      if (child === null || child === undefined) continue;
      if (Array.isArray(child)) {
        for (const c of child) if (c !== null && c !== undefined) node.append(c);
      } else {
        node.append(child.nodeType ? child : document.createTextNode(String(child)));
      }
    }
    return node;
  }

  /** Small colored tag. tone: neutral | positive | info | warning | negative. */
  function badge(text, tone) {
    return el("span", { class: `badge badge--${tone || "neutral"}` }, text);
  }

  function confidenceBadge(confidence) {
    const tone = { HIGH: "positive", MEDIUM: "info", LOW: "warning" }[confidence] || "neutral";
    return badge(t("wizard.confidence", { level: confidence }), tone);
  }

  /**
   * Candidate card for one role option.
   *
   * @param {object}  opts
   * @param {object}  opts.candidate    candidate from mock data
   * @param {boolean} opts.isRecommended true when this is the recommended option
   * @param {boolean} opts.selected     true when currently selected
   * @param {Function} opts.onSelect    called with the candidate id
   * @param {boolean} opts.confirmed    confirmation state (important bindings only)
   * @param {Function} opts.onConfirm   called with the checkbox state
   * @param {string}  opts.roleLabel    human role label for the confirmation text
   */
  function candidateCard({ candidate, isRecommended, selected, onSelect, confirmed, onConfirm, roleLabel }) {
    const card = el("div", { class: `candidate ${selected ? "candidate--selected" : ""}` });

    const head = el("label", { class: "candidate__head" },
      el("input", {
        type: "radio",
        name: candidate.id,
        checked: selected,
        onchange: () => onSelect(candidate.id),
      }),
      el("span", { class: "candidate__name" }, candidate.name),
      isRecommended ? badge(t("wizard.recommended"), "positive") : badge(t("wizard.alternative"), "neutral"),
    );

    const meta = el("div", { class: "candidate__meta" },
      el("code", { class: "candidate__locator" }, candidate.locator),
      badge(candidate.identityQuality, candidate.identityQuality === "STABLE" ? "info" : "warning"),
      confidenceBadge(candidate.confidence),
    );

    const reasons = el("div", { class: "candidate__reasons" },
      el("span", { class: "candidate__reasons-label" }, t("wizard.reasons")),
      candidate.reasons.map((r) => badge(r, "neutral")),
    );

    const evidence = el("p", { class: "candidate__evidence" }, candidate.evidence);

    card.append(head, meta, reasons, evidence);

    // Confirmation is bound to the exact selected reference, so it is only
    // offered for the selected candidate. Switching candidates removes it.
    if (onConfirm && selected) {
      card.append(
        el("label", { class: "candidate__confirm" },
          el("input", { type: "checkbox", checked: confirmed, onchange: (e) => onConfirm(e.target.checked) }),
          el("span", {},
            t("wizard.confirm_binding", { name: candidate.name, role: roleLabel })
          )
        )
      );
    }

    return card;
  }

  /** Step indicator. steps: [{id, label}], currentId: number. */
  function stepper(steps, currentId, onStepClick) {
    return el("ol", { class: "stepper__list" },
      steps.map((s) => {
        const state = s.id < currentId ? "done" : s.id === currentId ? "current" : "upcoming";
        return el("li", {
          class: `stepper__step stepper__step--${state}`,
          onclick: () => onStepClick(s.id),
        },
          el("span", { class: "stepper__index" }, s.id),
          el("span", { class: "stepper__label" }, s.label),
        );
      })
    );
  }

  /** One validation issue row. issue: {severity, code, message}. */
  function validationItem(issue) {
    const tone = { blocking: "negative", warning: "warning", info: "info" }[issue.severity] || "neutral";
    return el("li", { class: `validation-item validation-item--${issue.severity}` },
      badge(issue.severity.toUpperCase(), tone),
      el("code", { class: "validation-item__code" }, issue.code),
      el("span", { class: "validation-item__message" }, issue.message),
    );
  }

  /** Key/value row for summaries and review tables. */
  function kvRow(label, value) {
    return el("div", { class: "kv" },
      el("span", { class: "kv__label" }, label),
      el("span", { class: "kv__value" }, value),
    );
  }

  /** Callout box. tone: neutral | info | warning | positive | negative. */
  function noteBox(text, tone) {
    return el("div", { class: `note note--${tone || "neutral"}` }, text);
  }

  // ============================================================ app shell

  /**
   * Display metadata for Controlel states. States are explicit strings from
   * the (mock) data layer; unknown states render neutrally rather than being
   * guessed.
   */
  // `key` is the stable translation key for the label; the state string
  // itself stays the machine-facing identity.
  const STATE_META = {
    active: { label: "Active", tone: "positive", key: "state.active" },
    configured: { label: "Configured", tone: "positive", key: "state.configured" },
    incomplete: { label: "Incomplete setup", tone: "warning", key: "state.incomplete_setup" },
    attention: { label: "Needs attention", tone: "negative", key: "state.attention" },
    disabled: { label: "Disabled", tone: "neutral", key: "state.disabled" },
    not_configured: { label: "Not configured", tone: "neutral", key: "state.not_configured" },
    ok: { label: "OK", tone: "positive", key: "state.ok" },
    idle: { label: "Idle", tone: "neutral", key: "state.idle" },
    unknown: { label: "Unknown", tone: "neutral", key: "state.unknown" },
    // Frontend API v1 vocabulary (real backend states).
    inactive: { label: "Inactive", tone: "neutral", key: "state.inactive" },
    error: { label: "Error", tone: "negative", key: "state.error" },
    degraded: { label: "Degraded", tone: "warning", key: "state.degraded" },
    stopped: { label: "Stopped", tone: "neutral", key: "state.stopped" },
    ready: { label: "Ready", tone: "positive", key: "state.ready" },
    invalid: { label: "Invalid", tone: "negative", key: "state.invalid" },
  };

  /**
   * {label, tone} for a state string (public contract; unknown states stay
   * neutral). The map entries also carry a translation `key`, which
   * statusBadge() resolves; stateMeta() itself stays key-free.
   */
  function stateMeta(state) {
    const meta = STATE_META[state];
    if (!meta) return { label: String(state), tone: "neutral" };
    return { label: meta.label, tone: meta.tone };
  }

  /** Status badge for a Controlel state. label overrides the default text. */
  function statusBadge(state, label) {
    const meta = STATE_META[state] || { label: String(state), tone: "neutral" };
    const text = label || (meta.key && has(meta.key) ? t(meta.key) : meta.label);
    return badge(text, meta.tone);
  }

  /**
   * Page header: title, optional subtitle, badges and action buttons.
   * @param {object} opts {title, subtitle, badges: [node], actions: [node]}
   */
  function pageHeader({ title, subtitle, badges, actions }) {
    return el("header", { class: "page-header" },
      el("div", { class: "page-header__main" },
        el("h2", { class: "page-header__title" }, title),
        subtitle ? el("p", { class: "page-header__subtitle" }, subtitle) : null,
        badges && badges.length ? el("div", { class: "page-header__badges" }, badges) : null
      ),
      actions && actions.length ? el("div", { class: "page-header__actions" }, actions) : null
    );
  }

  /**
   * Section / card container.
   * @param {object} opts {title, lead, badges, actions, children, className}
   */
  function section({ title, lead, badges, actions, children, className }) {
    return el("section", { class: `section ${className || ""}`.trim() },
      el("div", { class: "section__head" },
        el("h3", { class: "section__title" }, title),
        badges && badges.length ? el("div", { class: "section__badges" }, badges) : null
      ),
      lead ? el("p", { class: "section__lead" }, lead) : null,
      children,
      actions && actions.length ? el("div", { class: "section__actions" }, actions) : null
    );
  }

  /**
   * Metric / value card.
   * @param {object} opts {label, value, unit, sub, tone}
   */
  function metricCard({ label, value, unit, sub, tone }) {
    return el("div", { class: `metric ${tone ? `metric--${tone}` : ""}`.trim() },
      el("span", { class: "metric__label" }, label),
      el("span", { class: "metric__value" },
        value,
        unit ? el("span", { class: "metric__unit" }, unit) : null
      ),
      sub ? el("span", { class: "metric__sub" }, sub) : null
    );
  }

  /**
   * Reusable module card: status, short summary, warning count and up to two
   * actions. The action objects come from the data layer as
   * {label, route}; onNavigate(route) is provided by the view.
   *
   * @param {object} opts {module, onNavigate}
   */
  function moduleCard({ module, onNavigate }) {
    const primary = module.primaryAction || null;
    const secondary = module.secondaryAction || null;

    const actions = [];
    if (primary) {
      actions.push(el("button", {
        class: "btn btn--primary btn--sm",
        "data-action": "primary",
        onclick: () => onNavigate(primary.route),
      }, primary.label));
    }
    if (secondary) {
      actions.push(el("button", {
        class: "btn btn--secondary btn--sm",
        "data-action": "secondary",
        onclick: () => onNavigate(secondary.route),
      }, secondary.label));
    }

    return el("article", { class: "module-card", "data-module": module.id },
      el("div", { class: "module-card__head" },
        el("h3", { class: "module-card__title" }, module.label),
        statusBadge(module.state, module.stateLabel)
      ),
      el("p", { class: "module-card__summary" }, module.summary),
      el("div", { class: "module-card__meta" },
        module.warningCount > 0
          ? badge(t("module.warnings", { count: module.warningCount }), "warning")
          : badge(t("module.no_warnings"), "neutral"),
        module.updatedAt ? el("span", { class: "module-card__updated" }, t("module.updated", { time: module.updatedAt })) : null
      ),
      actions.length ? el("div", { class: "module-card__actions" }, actions) : null
    );
  }

  /**
   * Issue / warning panel.
   * @param {object} opts {title, issues: [{severity, code, message}], emptyMessage}
   */
  function issuePanel({ title, issues, emptyMessage }) {
    const list = issues || [];
    if (list.length === 0) {
      return el("div", { class: "section issue-panel issue-panel--empty" },
        el("h3", { class: "section__title" }, title || t("common.issues")),
        el("p", { class: "section__lead" }, emptyMessage || t("common.no_issues"))
      );
    }
    const tone = { warning: "warning", negative: "negative", info: "info" };
    return el("div", { class: "section issue-panel" },
      el("div", { class: "section__head" },
        el("h3", { class: "section__title" }, title || t("common.issues")),
        badge(`${list.length}`, list.some((i) => i.severity === "negative") ? "negative" : "warning")
      ),
      el("ul", { class: "issue-list" },
        list.map((issue) => el("li", { class: `issue issue--${issue.severity || "warning"}` },
          badge(String(issue.severity || "warning").toUpperCase(), tone[issue.severity] || "warning"),
          el("span", { class: "issue__message" }, issue.message),
          issue.code ? el("code", { class: "issue__code" }, issue.code) : null
        ))
      )
    );
  }

  const LEVEL_TONE = { basic: "neutral", detailed: "info", debug: "warning" };

  /**
   * Activity / event row. Technical reason codes and raw metadata are kept
   * behind an expandable Details block.
   *
   * @param {object} opts {event, expanded, onToggle}
   */
  function activityRow({ event, expanded, onToggle }) {
    const hasDetails =
      (event.reasonCodes && event.reasonCodes.length > 0) ||
      (event.metadata && Object.keys(event.metadata).length > 0);

    const details = [];
    if (event.reasonCodes && event.reasonCodes.length > 0) {
      details.push(el("div", { class: "activity-details__block" },
        el("span", { class: "activity-details__label" }, t("activity.reason_codes")),
        el("div", { class: "activity-details__codes" },
          event.reasonCodes.map((code) => badge(code, "neutral"))
        )
      ));
    }
    if (event.metadata && Object.keys(event.metadata).length > 0) {
      details.push(el("div", { class: "activity-details__block" },
        el("span", { class: "activity-details__label" }, t("activity.raw_metadata")),
        el("pre", { class: "activity-details__meta" }, JSON.stringify(event.metadata, null, 2))
      ));
    }

    return el("li", { class: `activity-row activity-row--${event.level}`, "data-event": event.id },
      el("div", { class: "activity-row__main" },
        el("time", { class: "activity-row__time" }, event.at),
        el("div", { class: "activity-row__body" },
          el("div", { class: "activity-row__title" },
            el("span", { class: "activity-row__name" }, event.title),
            badge(event.level.toUpperCase(), LEVEL_TONE[event.level] || "neutral")
          ),
          el("p", { class: "activity-row__message" }, event.message)
        ),
        hasDetails ? el("button", {
          class: "btn btn--link btn--sm",
          "aria-expanded": expanded ? "true" : "false",
          onclick: onToggle,
        }, expanded ? t("common.hide_details") : t("common.details")) : null
      ),
      hasDetails ? el("div", { class: "activity-row__details", hidden: !expanded }, details) : null
    );
  }

  /**
   * Empty state.
   * @param {object} opts {title, message, action}
   */
  function emptyState({ title, message, action }) {
    return el("div", { class: "empty-state" },
      el("div", { class: "empty-state__icon" }, "—"),
      el("h3", { class: "empty-state__title" }, title),
      message ? el("p", { class: "empty-state__message" }, message) : null,
      action ? el("div", { class: "empty-state__action" }, action) : null
    );
  }

  /**
   * Application navigation list.
   * items: [{id, label, order, hidden}] (already filtered/sorted by the view).
   */
  function navList({ items, currentId, onNavigate }) {
    return el("nav", { class: "app-nav", "aria-label": t("navigation.aria_label") },
      el("ul", { class: "app-nav__list" },
        items.map((item) => el("li", { class: "app-nav__item-wrap" },
          el("button", {
            class: `app-nav__item ${item.id === currentId ? "app-nav__item--current" : ""}`,
            "data-route": item.id,
            "aria-current": item.id === currentId ? "page" : null,
            onclick: () => onNavigate(item.id),
          }, item.label)
        ))
      )
    );
  }

  global.CW = {
    el, badge, confidenceBadge, candidateCard, stepper, validationItem, kvRow, noteBox,
    STATE_META, stateMeta, statusBadge, pageHeader, section, metricCard,
    moduleCard, issuePanel, activityRow, emptyState, navList,
  };
})(typeof window !== "undefined" ? window : globalThis);
