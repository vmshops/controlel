/*
 * Controlel setup wizard — state, validation and step rendering.
 *
 * Lifecycle concepts (kept distinct, per the setup architecture):
 *   - snapshot: what the (mock) discovery observed;
 *   - draft:    the user's editable selections (may be incomplete);
 *   - validation: deterministic assessment of the exact draft;
 *   - activation: only possible when validation is activation-ready.
 *
 * Prototype constraints: mock data only, no backend calls, draft state is
 * in-memory and lost on reload.
 */
(function () {
  "use strict";

  const { el, badge, candidateCard, stepper, validationItem, kvRow, noteBox } = window.CW;
  const data = window.MOCK_SETUP_DATA;

  // i18n (i18n.js): translated text is presentation only. Reason codes, ids
  // and revision identifiers stay untranslated.
  const CI18N = window.CI18N;
  const t = CI18N ? (key, params) => CI18N.t(key, params) : (key) => key;

  // Step labels are resolved at render time so a language switch applies.
  const STEPS = [
    { id: 1, key: "wizard.step_discovery" },
    { id: 2, key: "wizard.step_zone" },
    { id: 3, key: "wizard.step_sensor" },
    { id: 4, key: "wizard.step_review" },
  ];

  const state = {
    step: 1,
    snapshot: data.snapshot,
    draft: {
      zone: null,
      sensor: null,
      heatSource: null,
      sensorConfirmed: false,
      heatSourceConfirmed: false,
    },
    draftSavedAt: null,
    activation: null,
  };

  const panel = document.getElementById("step-panel");
  const stepperNav = document.getElementById("stepper");
  const footer = document.getElementById("wizard-footer");
  const draftStatus = document.getElementById("draft-status");

  // ---------------------------------------------------------------- helpers

  function roleData(role) {
    return data.roles[role];
  }

  function candidate(role, id) {
    return roleData(role).candidates.find((c) => c.id === id);
  }

  function originFor(role) {
    const id = state.draft[role];
    if (!id) return null;
    return id === roleData(role).recommendedId ? "RECOMMENDATION_ACCEPTED" : "MANUAL";
  }

  function formatTime(iso) {
    return new Date(iso).toLocaleString();
  }

  // ------------------------------------------------------------------ draft

  /** Any draft edit invalidates a previous activation (new draft revision). */
  function touchDraft() {
    state.activation = null;
  }

  function selectZone(id) {
    state.draft.zone = id;
    touchDraft();
    render();
  }

  function selectSensor(id) {
    state.draft.sensor = id;
    state.draft.sensorConfirmed = false; // a new selection needs a fresh confirmation
    touchDraft();
    render();
  }

  function selectHeatSource(id) {
    state.draft.heatSource = id;
    state.draft.heatSourceConfirmed = false;
    touchDraft();
    render();
  }

  function setSensorConfirmed(value) {
    state.draft.sensorConfirmed = value;
    render();
  }

  function setHeatSourceConfirmed(value) {
    state.draft.heatSourceConfirmed = value;
    render();
  }

  // ------------------------------------------------------------- validation

  /**
   * Deterministic validation of the exact current draft.
   * Returns { issues, blocking, warnings, activationReady }.
   */
  function validateDraft() {
    const issues = [];
    const d = state.draft;

    if (!d.zone) {
      issues.push({ severity: "blocking", code: "ZONE_REQUIRED", message: t("wizard.issue_zone_required") });
    }
    if (!d.sensor) {
      issues.push({ severity: "blocking", code: "SENSOR_REQUIRED", message: t("wizard.issue_sensor_required") });
    } else if (!d.sensorConfirmed) {
      issues.push({
        severity: "blocking",
        code: "SENSOR_CONFIRMATION_REQUIRED",
        message: t("wizard.issue_sensor_confirmation"),
      });
    }
    if (!d.heatSource) {
      issues.push({ severity: "blocking", code: "HEAT_SOURCE_REQUIRED", message: t("wizard.issue_heat_source_required") });
    } else if (!d.heatSourceConfirmed) {
      issues.push({
        severity: "blocking",
        code: "HEAT_SOURCE_CONFIRMATION_REQUIRED",
        message: t("wizard.issue_heat_source_confirmation"),
      });
    }

    if (d.zone && d.sensor) {
      const zone = candidate("zone", d.zone);
      const sensor = candidate("sensor", d.sensor);
      if (zone.area !== sensor.area) {
        issues.push({
          severity: "warning",
          code: "SENSOR_AREA_MISMATCH",
          message: t("wizard.issue_area_mismatch", { sensor: sensor.area, zone: zone.area }),
        });
      }
    }

    if (d.heatSource && candidate("heatSource", d.heatSource).identityQuality === "EPHEMERAL") {
      issues.push({
        severity: "warning",
        code: "HEAT_SOURCE_EPHEMERAL",
        message: t("wizard.issue_ephemeral"),
      });
    }

    const blocking = issues.filter((i) => i.severity === "blocking");
    const warnings = issues.filter((i) => i.severity === "warning");
    return { issues, blocking, warnings, activationReady: blocking.length === 0 };
  }

  // ----------------------------------------------------------------- actions

  function saveDraft() {
    state.draftSavedAt = new Date().toISOString();
    render();
  }

  function activate() {
    if (!validateDraft().activationReady) return;
    state.activation = {
      at: new Date().toISOString(),
      revisionId: "rev-" + Math.random().toString(36).slice(2, 8),
    };
    render();
  }

  function refreshSnapshot() {
    const now = new Date();
    state.snapshot = {
      ...state.snapshot,
      snapshotId: "snap-" + now.toISOString().slice(0, 10).replace(/-/g, "") + "-" + now.toTimeString().slice(0, 5).replace(":", ""),
      capturedAt: now.toISOString(),
      fingerprint: "sha256:" + Math.random().toString(16).slice(2, 10) + "…" + Math.random().toString(16).slice(2, 6),
    };
    render();
  }

  // Map a validation reason code to the wizard step that resolves it.
  // Reason codes stay structured internally; this only drives navigation.
  const CODE_STEP = {
    ZONE_REQUIRED: 2,
    SENSOR_REQUIRED: 3,
    SENSOR_CONFIRMATION_REQUIRED: 3,
    HEAT_SOURCE_REQUIRED: 3,
    HEAT_SOURCE_CONFIRMATION_REQUIRED: 3,
  };

  function stepLabel(id) {
    const s = STEPS.find((x) => x.id === id);
    return s ? t(s.key) : "";
  }

  function goToStep(id) {
    state.step = id;
    render();
  }

  /**
   * "Check readiness" is always pressable. When the draft is activation-ready
   * the same action performs the mock activation; otherwise it surfaces the
   * blocking summary on the review step. An incomplete setup can never
   * activate — it can only be saved and finished later.
   */
  function checkReadiness() {
    if (validateDraft().activationReady) {
      activate();
    } else {
      goToStep(4);
    }
  }

  // ---------------------------------------------------------------- rendering

  function render() {
    renderStepper();
    renderStep();
    renderFooter();
    renderDraftStatus();
  }

  function renderStepper() {
    stepperNav.setAttribute("aria-label", t("panel.setup_steps"));
    stepperNav.replaceChildren(stepper(STEPS.map((s) => ({ id: s.id, label: t(s.key) })), state.step, (id) => {
      state.step = id;
      render();
    }));
  }

  function renderStep() {
    panel.replaceChildren();
    if (state.step === 1) panel.append(renderDiscovery());
    else if (state.step === 2) panel.append(renderZone());
    else if (state.step === 3) panel.append(renderBindings());
    else panel.append(renderReview());
  }

  function renderDraftStatus() {
    const report = validateDraft();
    draftStatus.hidden = false;
    const saved = state.draftSavedAt ? t("wizard.saved", { time: formatTime(state.draftSavedAt) }) : t("wizard.not_saved");
    draftStatus.replaceChildren(
      report.blocking.length === 0
        ? badge(t("wizard.complete"), "positive")
        : badge(t("wizard.incomplete", { count: report.blocking.length }), "warning"),
      el("span", { class: "draft-status__text" }, `${saved} · ${t("wizard.in_memory")}`)
    );
  }

  // Step 1 — discovery summary

  function renderDiscovery() {
    const s = state.snapshot;
    const counts = [
      [t("wizard.count_floors"), s.counts.floors],
      [t("wizard.count_areas"), s.counts.areas],
      [t("wizard.count_devices"), s.counts.devices],
      [t("wizard.count_entities"), s.counts.entities],
    ];

    return el("div", { class: "step" },
      el("h2", { class: "step__title" }, t("wizard.discovery_title")),
      el("p", { class: "step__lead" }, t("wizard.discovery_lead")),

      el("div", { class: "panel" },
        el("h3", { class: "panel__title" }, t("wizard.snapshot")),
        el("div", { class: "kv-grid" },
          kvRow(t("wizard.provider"), s.provider),
          kvRow(t("wizard.instance"), s.providerInstanceId),
          kvRow(t("wizard.snapshot_id"), s.snapshotId),
          kvRow(t("wizard.captured_at"), formatTime(s.capturedAt)),
          kvRow(t("wizard.adapter_version"), s.adapterVersion),
          kvRow(t("wizard.fingerprint"), s.fingerprint),
        ),
        el("div", { class: "count-grid" },
          counts.map(([label, value]) =>
            el("div", { class: "count" },
              el("span", { class: "count__value" }, value),
              el("span", { class: "count__label" }, label)
            )
          )
        ),
        el("div", { class: "panel__actions" },
          el("button", { class: "btn btn--secondary", onclick: refreshSnapshot }, t("wizard.refresh_snapshot"))
        )
      ),

      noteBox(t("wizard.discovery_note"), "info")
    );
  }

  // Step 2 — zone selection

  function renderZone() {
    const role = roleData("zone");
    return el("div", { class: "step" },
      el("h2", { class: "step__title" }, t("wizard.zone_title")),
      el("p", { class: "step__lead" }, t("wizard.zone_lead")),

      el("div", { class: "candidate-list" },
        role.candidates.map((c) =>
          candidateCard({
            candidate: c,
            isRecommended: c.id === role.recommendedId,
            selected: state.draft.zone === c.id,
            onSelect: selectZone,
          })
        )
      )
    );
  }

  // Step 3 — sensor + heat source

  function renderRoleSection(roleKey, heading, lead) {
    const role = roleData(roleKey);
    const selectedId = state.draft[roleKey];
    const confirmed = roleKey === "sensor" ? state.draft.sensorConfirmed : state.draft.heatSourceConfirmed;
    const onSelect = roleKey === "sensor" ? selectSensor : selectHeatSource;
    const onConfirm = roleKey === "sensor" ? setSensorConfirmed : setHeatSourceConfirmed;

    return el("div", { class: "panel" },
      el("h3", { class: "panel__title" }, heading),
      el("p", { class: "panel__lead" }, lead),
      el("div", { class: "candidate-list" },
        role.candidates.map((c) =>
          candidateCard({
            candidate: c,
            isRecommended: c.id === role.recommendedId,
            selected: selectedId === c.id,
            onSelect,
            confirmed,
            onConfirm: role.important ? onConfirm : null,
            roleLabel: heading,
          })
        )
      ),
      role.important && selectedId && !confirmed
        ? noteBox(t("wizard.important_binding_note"), "warning")
        : null
    );
  }

  function renderBindings() {
    return el("div", { class: "step" },
      el("h2", { class: "step__title" }, t("wizard.bindings_title")),
      el("p", { class: "step__lead" }, t("wizard.bindings_lead")),
      renderRoleSection("sensor", t("wizard.role_sensor"), t("wizard.sensor_lead")),
      renderRoleSection("heatSource", t("wizard.role_heat_source"), t("wizard.heat_source_lead"))
    );
  }

  // Step 4 — review + validation + activation

  function renderReviewRow(roleKey, label) {
    const id = state.draft[roleKey];
    if (!id) {
      return el("div", { class: "review-row review-row--missing" },
        el("span", { class: "review-row__label" }, label),
        badge(t("wizard.not_selected"), "warning"),
        el("span", { class: "review-row__value" }, "—")
      );
    }
    const c = candidate(roleKey, id);
    const origin = originFor(roleKey);
    const confirmed = roleKey === "sensor" ? state.draft.sensorConfirmed : roleKey === "heatSource" ? state.draft.heatSourceConfirmed : null;

    return el("div", { class: "review-row" },
      el("span", { class: "review-row__label" }, label),
      el("span", { class: "review-row__value" },
        el("strong", {}, c.name),
        el("code", { class: "review-row__locator" }, c.locator)
      ),
      el("span", { class: "review-row__badges" },
        badge(origin, origin === "RECOMMENDATION_ACCEPTED" ? "info" : "neutral"),
        badge(c.identityQuality, c.identityQuality === "STABLE" ? "info" : "warning"),
        confirmed === true ? badge(t("wizard.confirmed"), "positive") : confirmed === false ? badge(t("wizard.not_confirmed"), "negative") : null
      )
    );
  }

  function readinessPanel(report) {
    if (state.activation) {
      return el("div", { class: "panel readiness readiness--active" },
        el("h3", { class: "panel__title" }, t("wizard.activation")),
        badge(t("wizard.activation_recorded"), "positive"),
        el("div", { class: "kv-grid" },
          kvRow(t("wizard.revision"), state.activation.revisionId),
          kvRow(t("wizard.at"), formatTime(state.activation.at))
        ),
        noteBox(t("wizard.activation_note"), "info")
      );
    }

    if (report.activationReady) {
      return el("div", { class: "panel readiness readiness--ready" },
        el("h3", { class: "panel__title" }, t("wizard.readiness")),
        noteBox(t("wizard.ready_note"), "positive"),
        el("div", { class: "panel__actions" },
          el("button", { class: "btn btn--primary", onclick: checkReadiness }, t("wizard.activate")),
          el("span", { class: "hint" }, t("wizard.activate_hint"))
        )
      );
    }

    const items = report.blocking.map((issue) => {
      const step = CODE_STEP[issue.code] || 4;
      return el("li", { class: "readiness-item" },
        el("div", { class: "readiness-item__main" },
          badge(issue.code, "negative"),
          el("span", { class: "readiness-item__message" }, issue.message)
        ),
        el("button", { class: "btn btn--link", onclick: () => goToStep(step) }, t("wizard.fix_in_step", { step, label: stepLabel(step) }))
      );
    });

    return el("div", { class: "panel readiness readiness--blocked" },
      el("h3", { class: "panel__title" }, t("wizard.readiness")),
      noteBox(t("wizard.incomplete_note", { count: report.blocking.length }), "warning"),
      el("ul", { class: "readiness-list" }, items),
      el("div", { class: "panel__actions" },
        el("button", { class: "btn btn--primary", onclick: checkReadiness }, t("wizard.check_readiness")),
        el("span", { class: "hint" }, t("wizard.cannot_activate"))
      )
    );
  }

  function renderReview() {
    const report = validateDraft();

    const review = el("div", { class: "panel" },
      el("h3", { class: "panel__title" }, t("wizard.draft_review")),
      renderReviewRow("zone", t("wizard.zone")),
      renderReviewRow("sensor", t("wizard.role_sensor")),
      renderReviewRow("heatSource", t("wizard.role_heat_source")),
      noteBox(t("wizard.validation_note"), "neutral")
    );

    const validation = el("div", { class: "panel" },
      el("h3", { class: "panel__title" }, t("wizard.validation_report")),
      report.issues.length === 0
        ? noteBox(t("wizard.validation_passed"), "positive")
        : el("ul", { class: "validation-list" }, report.issues.map(validationItem)),
      report.warnings.length > 0 && report.blocking.length === 0
        ? noteBox(t("wizard.warnings_recorded", { count: report.warnings.length }), "warning")
        : null
    );

    const readiness = readinessPanel(report);

    return el("div", { class: "step" },
      el("h2", { class: "step__title" }, t("wizard.review_title")),
      el("p", { class: "step__lead" }, t("wizard.review_lead")),
      review,
      validation,
      readiness
    );
  }

  // ----------------------------------------------------------------- footer

  function renderFooter() {
    const report = validateDraft();
    const back = el("button", {
      class: "btn btn--ghost",
      disabled: state.step === 1,
      onclick: () => { state.step -= 1; render(); },
    }, t("wizard.back"));

    const save = el("button", { class: "btn btn--secondary", onclick: saveDraft }, t("wizard.save_later"));

    let primary;
    if (state.step < 4) {
      primary = el("button", { class: "btn btn--primary", onclick: () => { state.step += 1; render(); } }, t("wizard.continue"));
    } else {
      // Always pressable: "Activate" when ready, "Check readiness" when not.
      primary = el("button", {
        class: "btn btn--primary",
        onclick: checkReadiness,
      }, report.activationReady ? t("wizard.activate") : t("wizard.check_readiness"));
    }

    footer.replaceChildren(back, save, primary);
  }

  // -------------------------------------------------------------------- init

  render();
})();
