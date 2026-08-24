/*
 * Controlel setup wizard — real Setup Write API v1 consumer.
 *
 * The backend owns discovery, recommendations, draft persistence, and
 * validation. This file renders those contracts and submits explicit user
 * selections. It never activates/canonicalizes configuration, calls Home
 * Assistant services, or substitutes mock data after a backend failure.
 */
(function (global) {
  "use strict";

  const PRIMARY_TEMPERATURE_ROLE = "heating.primary_temperature";
  const SOURCE_ENABLE_TARGET_ROLE = "heating.source.enable_target";
  const SOURCE_DISABLE_TARGET_ROLE = "heating.source.disable_target";
  const AREA_KIND = "home_assistant.area";
  const STEPS = [
    { id: 1, key: "wizard.step_discovery" },
    { id: 2, key: "wizard.step_zone" },
    { id: 3, key: "wizard.step_sensor" },
    { id: 4, key: "wizard.step_review" },
  ];
  let idSequence = 0;

  function defaultId(prefix) {
    if (global.crypto && typeof global.crypto.randomUUID === "function") {
      return `${prefix}-${global.crypto.randomUUID()}`;
    }
    idSequence += 1;
    return `${prefix}-${Date.now()}-${idSequence}`;
  }

  function candidateView(candidate) {
    const locator = candidate.current_locator || candidate.native_id || "Unknown locator";
    return {
      id: candidate.candidate_id,
      name: locator,
      locator,
      identityQuality: candidate.identity_quality,
      confidence: candidate.confidence,
      reasons: candidate.reason_codes || [],
      evidence: JSON.stringify(candidate.evidence || {}),
    };
  }

  function recommendationCandidates(recommendation) {
    if (!recommendation) return [];
    return [recommendation.recommended, ...(recommendation.alternatives || [])].filter(Boolean);
  }

  function createSetupWizard(options) {
    const opts = options && typeof options === "object" ? options : {};
    const client = opts.client;
    const root = opts.root || global.document;
    const CW = global.CW;
    if (!client || !CW || !root) return null;

    const { el, badge, candidateCard, stepper, validationItem, kvRow, noteBox } = CW;
    const CI18N = global.CI18N;
    const t = CI18N ? (key, params) => CI18N.t(key, params) : (key) => key;
    const panel = opts.panel || root.getElementById("step-panel");
    const stepperNav = opts.stepper || root.getElementById("stepper");
    const footer = opts.footer || root.getElementById("wizard-footer");
    const draftStatus = opts.draftStatus || root.getElementById("draft-status");
    if (!panel || !stepperNav || !footer || !draftStatus) return null;

    const now = typeof opts.now === "function" ? opts.now : () => new Date().toISOString();
    const makeId = typeof opts.idFactory === "function" ? opts.idFactory : defaultId;
    const storage = opts.storage || null;
    const storageKey = `controlel.setup.draft.v1.${opts.configEntryId || "unknown"}`;
    const state = {
      step: 1,
      status: "idle",
      error: null,
      errorOperation: null,
      snapshot: null,
      recommendations: [],
      session: null,
      dirty: false,
      lastSavedAt: null,
      draft: { areaId: null, selections: {}, confirmations: {} },
    };

    function storedDraftId() {
      try {
        return storage && typeof storage.getItem === "function" ? storage.getItem(storageKey) : null;
      } catch (_error) {
        return null;
      }
    }

    function storeDraftId(draftId) {
      try {
        if (storage && typeof storage.setItem === "function") storage.setItem(storageKey, draftId);
      } catch (_error) {
        // Backend persistence remains authoritative if browser storage is unavailable.
      }
    }

    function clearStoredDraftId() {
      try {
        if (storage && typeof storage.removeItem === "function") storage.removeItem(storageKey);
      } catch (_error) {
        // The backend error stays visible; no fallback data is introduced.
      }
    }

    function recommendation(role) {
      return state.recommendations.find((item) => item.role === role) || null;
    }

    function candidate(role, candidateId) {
      return recommendationCandidates(recommendation(role)).find((item) => item.candidate_id === candidateId) || null;
    }

    function areas() {
      return state.snapshot ? state.snapshot.objects.filter((item) => item.object_kind === AREA_KIND) : [];
    }

    function applySession(session) {
      state.session = session;
      state.snapshot = session.discovery;
      state.recommendations = session.recommendations;
      state.draft.areaId = typeof session.settings.zone_id === "string" ? session.settings.zone_id : state.draft.areaId;
      state.draft.selections = {};
      state.draft.confirmations = {};
      for (const selection of session.selections) {
        if (selection.candidate_id) state.draft.selections[selection.role] = selection.candidate_id;
        state.draft.confirmations[selection.role] = Boolean(selection.user_confirmed);
      }
      state.dirty = false;
    }

    function requestContext() {
      return { snapshot_id: makeId("snapshot"), captured_at: now() };
    }

    async function startDiscovery({ forceNewDraft = false } = {}) {
      state.status = "loading";
      state.error = null;
      state.errorOperation = null;
      render();
      const context = requestContext();
      try {
        const [snapshot, recommendations] = await Promise.all([
          client.discover(context),
          client.recommendations(context),
        ]);
        state.snapshot = snapshot;
        state.recommendations = recommendations;
        const existingDraftId = forceNewDraft ? null : storedDraftId();
        let session;
        if (existingDraftId) {
          session = await client.reopenDraft({ draft_id: existingDraftId, ...context });
        } else {
          session = await client.startDraft({
            draft_id: makeId("draft"),
            module_instance_id: "main-heating",
            created_at: context.captured_at,
            snapshot_id: context.snapshot_id,
            report_id: makeId("report"),
            settings: {},
            selections: [],
          });
          storeDraftId(session.draft_id);
        }
        applySession(session);
        state.status = "loaded";
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "discovery";
      }
      render();
    }

    function startNewDraft() {
      clearStoredDraftId();
      state.session = null;
      state.draft = { areaId: null, selections: {}, confirmations: {} };
      return startDiscovery({ forceNewDraft: true });
    }

    function selectArea(areaId) {
      state.draft.areaId = areaId;
      state.dirty = true;
      render();
    }

    function selectCandidate(role, candidateId) {
      state.draft.selections[role] = candidateId;
      state.draft.confirmations[role] = false;
      state.dirty = true;
      render();
    }

    function confirmCandidate(role, value) {
      state.draft.confirmations[role] = Boolean(value);
      state.dirty = true;
      render();
    }

    function draftSettings() {
      const settings = {};
      const area = areas().find((item) => item.native_id === state.draft.areaId);
      if (area && area.native_id) {
        settings.zone_id = area.native_id;
        settings.zone_name = area.native_id;
      }
      const sensor = candidate(PRIMARY_TEMPERATURE_ROLE, state.draft.selections[PRIMARY_TEMPERATURE_ROLE]);
      if (sensor) {
        const identity = sensor.native_id || sensor.current_locator;
        if (identity) settings.sensor_id = identity;
        if (sensor.current_locator || sensor.native_id) settings.sensor_name = sensor.current_locator || sensor.native_id;
      }
      return settings;
    }

    function draftSelections() {
      return Object.entries(state.draft.selections).map(([role, candidateId]) => ({
        role,
        candidate_id: candidateId,
        user_confirmed: Boolean(state.draft.confirmations[role]),
      }));
    }

    async function saveDraft() {
      if (!state.session || state.status === "saving") return null;
      state.status = "saving";
      state.error = null;
      state.errorOperation = null;
      render();
      const updatedAt = now();
      try {
        const session = await client.updateDraft({
          draft_id: state.session.draft_id,
          expected_revision: state.session.draft_revision,
          updated_at: updatedAt,
          snapshot_id: state.snapshot.snapshot_id,
          report_id: makeId("report"),
          settings: draftSettings(),
          selections: draftSelections(),
        });
        applySession(session);
        state.lastSavedAt = updatedAt;
        state.status = "loaded";
        render();
        return session;
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "update";
        render();
        return null;
      }
    }

    async function validateDraft() {
      let session = state.session;
      const savedBeforeValidation = state.dirty;
      if (savedBeforeValidation) session = await saveDraft();
      if (!session || (savedBeforeValidation && state.status === "error")) return;
      state.status = "saving";
      state.error = null;
      state.errorOperation = null;
      render();
      const evaluatedAt = now();
      try {
        const validated = await client.validateDraft({
          draft_id: session.draft_id,
          snapshot_id: state.snapshot.snapshot_id,
          evaluated_at: evaluatedAt,
          report_id: makeId("report"),
        });
        applySession(validated);
        state.lastSavedAt = evaluatedAt;
        state.status = "loaded";
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "validate";
      }
      render();
    }

    function formatTime(value) {
      if (!value) return "Unknown";
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
    }

    function goToStep(step) {
      if (state.status !== "loaded" && step !== 1) return;
      state.step = step;
      render();
    }

    function renderStepper() {
      stepperNav.setAttribute("aria-label", t("panel.setup_steps"));
      stepperNav.replaceChildren(stepper(
        STEPS.map((item) => ({ id: item.id, label: t(item.key) })),
        state.step,
        goToStep
      ));
    }

    function renderDiscovery() {
      if (state.status === "idle") {
        return el("div", { class: "step" },
          el("h2", { class: "step__title" }, t("wizard.discovery_title")),
          el("p", { class: "step__lead" }, t("wizard.discovery_lead")),
          noteBox(t("wizard.not_discovered"), "neutral"),
          el("div", { class: "panel__actions" },
            el("button", { class: "btn btn--primary", onclick: () => startDiscovery() }, t("wizard.start_discovery"))
          )
        );
      }
      if (state.status === "loading") {
        return el("div", { class: "state-panel state-panel--loading" },
          el("p", { class: "state-panel__message" }, t("wizard.discovering"))
        );
      }
      if (state.status === "error") {
        return el("div", { class: "state-panel state-panel--error" },
          el("p", { class: "state-panel__title" }, t("wizard.discovery_unavailable")),
          el("p", { class: "state-panel__message" }, state.error && state.error.message ? state.error.message : "The setup request failed."),
          el("div", { class: "panel__actions" },
            el("button", { class: "btn btn--secondary", onclick: () => startDiscovery() }, t("common.retry")),
            storedDraftId() ? el("button", { class: "btn btn--ghost", onclick: startNewDraft }, t("wizard.start_new_draft")) : null
          )
        );
      }

      const snapshot = state.snapshot;
      const count = (kind) => snapshot.object_counts[kind] || 0;
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.discovery_title")),
        el("p", { class: "step__lead" }, t("wizard.discovery_lead")),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.snapshot")),
          el("div", { class: "kv-grid" },
            kvRow(t("wizard.provider"), snapshot.provider),
            kvRow(t("wizard.instance"), snapshot.provider_instance_id),
            kvRow(t("wizard.snapshot_id"), snapshot.snapshot_id),
            kvRow(t("wizard.captured_at"), formatTime(snapshot.captured_at)),
            kvRow(t("wizard.fingerprint"), snapshot.content_fingerprint),
            kvRow(t("wizard.draft"), state.session.draft_id),
            kvRow(t("wizard.revision"), String(state.session.draft_revision))
          ),
          el("div", { class: "count-grid" },
            [[t("wizard.count_floors"), count("home_assistant.floor")],
             [t("wizard.count_areas"), count(AREA_KIND)],
             [t("wizard.count_devices"), count("home_assistant.device")],
             [t("wizard.count_entities"), count("home_assistant.entity")]].map(([label, value]) =>
              el("div", { class: "count" },
                el("span", { class: "count__value" }, String(value)),
                el("span", { class: "count__label" }, label)
              )
            )
          ),
          el("div", { class: "panel__actions" },
            el("button", { class: "btn btn--secondary", onclick: () => startDiscovery() }, t("wizard.refresh_discovery"))
          )
        ),
        noteBox(t("wizard.discovery_note"), "info")
      );
    }

    function renderZone() {
      const discoveredAreas = areas();
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.zone_title")),
        el("p", { class: "step__lead" }, t("wizard.zone_lead")),
        discoveredAreas.length === 0
          ? noteBox(t("wizard.no_areas"), "warning")
          : el("div", { class: "candidate-list" }, discoveredAreas.map((area) => {
              const id = area.native_id;
              const selected = state.draft.areaId === id;
              return el("label", { class: `candidate ${selected ? "candidate--selected" : ""}` },
                el("span", { class: "candidate__head" },
                  el("input", { type: "radio", name: "setup-area", checked: selected, onchange: () => selectArea(id) }),
                  el("span", { class: "candidate__name" }, id || "Unknown area")
                ),
                el("span", { class: "candidate__meta" },
                  badge(area.identity_quality || "UNKNOWN", area.identity_quality === "STABLE" ? "info" : "warning"),
                  area.floor_id ? badge(area.floor_id, "neutral") : null
                )
              );
            }))
      );
    }

    function renderRole(role, heading, lead) {
      const item = recommendation(role);
      const candidates = recommendationCandidates(item);
      const selectedId = state.draft.selections[role];
      if (!item || candidates.length === 0) {
        return el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, heading),
          noteBox(t("wizard.no_candidates"), "warning")
        );
      }
      return el("div", { class: "panel" },
        el("h3", { class: "panel__title" }, heading),
        el("p", { class: "panel__lead" }, lead),
        el("div", { class: "candidate-list" }, candidates.map((entry) => candidateCard({
          candidate: candidateView(entry),
          isRecommended: Boolean(item.recommended && item.recommended.candidate_id === entry.candidate_id),
          selected: selectedId === entry.candidate_id,
          onSelect: (id) => selectCandidate(role, id),
          confirmed: Boolean(state.draft.confirmations[role]),
          onConfirm: item.explicit_confirmation_required ? (value) => confirmCandidate(role, value) : null,
          roleLabel: heading,
        }))),
        item.explicit_confirmation_required && selectedId && !state.draft.confirmations[role]
          ? noteBox(t("wizard.important_binding_note"), "warning")
          : null
      );
    }

    function renderBindings() {
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.bindings_title")),
        el("p", { class: "step__lead" }, t("wizard.bindings_lead")),
        renderRole(PRIMARY_TEMPERATURE_ROLE, t("wizard.role_sensor"), t("wizard.sensor_lead")),
        renderRole(SOURCE_ENABLE_TARGET_ROLE, t("wizard.source_enable_target"), t("wizard.heat_source_lead")),
        renderRole(SOURCE_DISABLE_TARGET_ROLE, t("wizard.source_disable_target"), t("wizard.heat_source_lead"))
      );
    }

    function reviewSelection(role, label) {
      const selected = candidate(role, state.draft.selections[role]);
      return el("div", { class: `review-row ${selected ? "" : "review-row--missing"}` },
        el("span", { class: "review-row__label" }, label),
        selected
          ? el("span", { class: "review-row__value" }, selected.current_locator || selected.native_id || "Unknown")
          : badge(t("wizard.not_selected"), "warning"),
        selected ? badge(state.draft.confirmations[role] ? t("wizard.confirmed") : t("wizard.not_confirmed"), state.draft.confirmations[role] ? "positive" : "negative") : null
      );
    }

    function renderReview() {
      const session = state.session;
      const issues = session.validation_issues || [];
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.review_title")),
        el("p", { class: "step__lead" }, t("wizard.review_persisted_lead")),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.draft_review")),
          el("div", { class: "review-row" },
            el("span", { class: "review-row__label" }, t("wizard.zone")),
            state.draft.areaId || badge(t("wizard.not_selected"), "warning")
          ),
          reviewSelection(PRIMARY_TEMPERATURE_ROLE, t("wizard.role_sensor")),
          reviewSelection(SOURCE_ENABLE_TARGET_ROLE, t("wizard.source_enable_target")),
          reviewSelection(SOURCE_DISABLE_TARGET_ROLE, t("wizard.source_disable_target")),
          state.dirty ? noteBox(t("wizard.unsaved_report"), "warning") : null
        ),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.validation_report")),
          el("div", { class: "section__badges" },
            badge(session.validation_status, session.validation_status === "CURRENT" ? "info" : "warning"),
            badge(t("wizard.blocking_count", { count: session.blocking_issue_count }), session.blocking_issue_count ? "negative" : "positive"),
            badge(t("wizard.warning_count", { count: session.warning_count }), session.warning_count ? "warning" : "neutral")
          ),
          issues.length
            ? el("ul", { class: "validation-list" }, issues.map((issue) => validationItem({
                severity: issue.severity === "ERROR" ? "blocking" : "warning",
                code: issue.code,
                message: issue.message_key,
              })))
            : noteBox(t("wizard.validation_passed"), "positive"),
          noteBox(t("wizard.validation_preparation"), "neutral")
        )
      );
    }

    function renderDraftStatus() {
      if (!state.session) {
        draftStatus.hidden = true;
        draftStatus.replaceChildren();
        return;
      }
      draftStatus.hidden = false;
      draftStatus.replaceChildren(
        badge(state.session.incomplete ? t("wizard.incomplete_draft") : t("wizard.draft_complete"), state.session.incomplete ? "warning" : "positive"),
        el("span", { class: "draft-status__text" },
          t("wizard.revision_status", {
            revision: state.session.draft_revision,
            status: state.dirty
              ? t("wizard.unsaved_edits")
              : state.lastSavedAt
                ? t("wizard.saved_revision", { time: formatTime(state.lastSavedAt) })
                : t("wizard.persisted"),
          })
        )
      );
    }

    function renderFooter() {
      const loaded = state.status === "loaded";
      const back = el("button", {
        class: "btn btn--ghost",
        disabled: state.step === 1 || !loaded,
        onclick: () => goToStep(state.step - 1),
      }, t("wizard.back"));
      const save = el("button", {
        class: "btn btn--secondary",
        disabled: !loaded || !state.session,
        onclick: saveDraft,
      }, state.status === "saving" ? t("wizard.saving") : t("wizard.save_later"));
      const next = el("button", {
        class: "btn btn--primary",
        disabled: !loaded || !state.session,
        onclick: state.step < 4 ? () => goToStep(state.step + 1) : validateDraft,
      }, state.step < 4 ? t("wizard.continue") : t("wizard.validate_draft"));
      footer.replaceChildren(back, save, next);
    }

    function render() {
      renderStepper();
      let content;
      if (state.step === 1) content = renderDiscovery();
      else if (state.step === 2) content = renderZone();
      else if (state.step === 3) content = renderBindings();
      else content = renderReview();
      if (state.status === "error" && state.step !== 1) {
        panel.replaceChildren(
          el("div", { class: "state-panel state-panel--error" },
            el("p", { class: "state-panel__title" }, t("wizard.draft_unavailable")),
            el("p", { class: "state-panel__message" }, state.error && state.error.message ? state.error.message : "The setup request failed."),
            el("button", {
              class: "btn btn--secondary",
              onclick: state.errorOperation === "validate" ? validateDraft : saveDraft,
            }, t("common.retry"))
          ),
          content
        );
      } else {
        panel.replaceChildren(content);
      }
      renderDraftStatus();
      renderFooter();
    }

    const api = {
      get state() { return state; },
      startDiscovery,
      startNewDraft,
      saveDraft,
      validateDraft,
      goToStep,
      render,
    };
    render();
    return api;
  }

  global.CA_WIZARD = {
    PRIMARY_TEMPERATURE_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    candidateView,
    recommendationCandidates,
    createSetupWizard,
  };
})(typeof window !== "undefined" ? window : globalThis);
