/*
 * Controlel setup wizard — reusable UI components (vanilla JS, no build step).
 *
 * Components are small, stateless render helpers. They receive data + event
 * callbacks and return DOM nodes; all state lives in wizard.js.
 */
(function (global) {
  "use strict";

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
    return badge(`Confidence: ${confidence}`, tone);
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
      isRecommended ? badge("Recommended", "positive") : badge("Alternative", "neutral"),
    );

    const meta = el("div", { class: "candidate__meta" },
      el("code", { class: "candidate__locator" }, candidate.locator),
      badge(candidate.identityQuality, candidate.identityQuality === "STABLE" ? "info" : "warning"),
      confidenceBadge(candidate.confidence),
    );

    const reasons = el("div", { class: "candidate__reasons" },
      el("span", { class: "candidate__reasons-label" }, "Reasons: "),
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
            `I confirm using “${candidate.name}” as the ${roleLabel}. ` +
            "This is an important binding; a successful command is not physical confirmation."
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

  global.CW = { el, badge, confidenceBadge, candidateCard, stepper, validationItem, kvRow, noteBox };
})(window);
