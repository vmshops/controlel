/*
 * Controlel Water Safety setup wizard ÔÇö Setup Write API v1 consumer.
 *
 * Explicit lifecycle: Save Draft -> Validate -> Canonicalize -> Activate.
 */
(function (global) {
  "use strict";

  const MOISTURE_SENSOR_ROLE = "water_safety.moisture_sensor";
  const NOTIFICATION_ROLE_PREFIX = "water_safety.notification.";
  const SIREN_ROLE_PREFIX = "water_safety.siren.";
  const DEFAULT_NOTIFICATION_ROLES = ["water_safety.notification.primary"];
  const AREA_KIND = "home_assistant.area";
  const STEP_COUNT = 7;
  const STEPS = [
    { id: 1, key: "wizard.water.step_discovery" },
    { id: 2, key: "wizard.water.step_area" },
    { id: 3, key: "wizard.water.step_sensor" },
    { id: 4, key: "wizard.water.step_notifications" },
    { id: 5, key: "wizard.water.step_sirens" },
    { id: 6, key: "wizard.water.step_settings" },
    { id: 7, key: "wizard.water.step_review" },
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

  function rolesWithPrefix(recommendations, prefix) {
    return recommendations
      .map((item) => item.role)
      .filter((role) => role && role.startsWith(prefix))
      .sort();
  }

  function createSetupWaterWizard(options) {
    const opts = options && typeof options === "object" ? options : {};
    const client = opts.client;
    const root = opts.root || global.document;
    const CW = global.CW;
    if (!client || !CW || !root) return null;

    const { el, badge, candidateCard, stepper, validationItem, kvRow, noteBox } = CW;
    const CI18N = global.CI18N;
    const t = CI18N ? (key, params) => CI18N.t(key, params) : (key) => key;
    const panel = opts.panel || root.getElementById("water-step-panel");
    const stepperNav = opts.stepper || root.getElementById("water-stepper");
    const footer = opts.footer || root.getElementById("water-wizard-footer");
    const draftStatus = opts.draftStatus || root.getElementById("water-draft-status");
    if (!panel || !stepperNav || !footer || !draftStatus) return null;

    const now = typeof opts.now === "function" ? opts.now : () => new Date().toISOString();
    const makeId = typeof opts.idFactory === "function" ? opts.idFactory : defaultId;
    const coreVersion = typeof opts.coreVersion === "string" && opts.coreVersion ? opts.coreVersion : "0.17.0";
    const integrationVersion = typeof opts.integrationVersion === "string" && opts.integrationVersion
      ? opts.integrationVersion
      : "0.17.0";
    const storage = opts.storage || null;
    const storageKey = `controlel.setup.water.draft.v1.${opts.configEntryId || "unknown"}`;
    const state = {
      step: 1,
      status: "idle",
      entryState: null,
      error: null,
      errorOperation: null,
      snapshot: null,
      recommendations: [],
      session: null,
      dirty: false,
      lastSavedAt: null,
      draft: {
        areaId: null,
        selections: {},
        confirmations: {},
        settings: {
          critical_sensor: false,
          unavailable_grace_seconds: 60,
          fault_repeat_interval_seconds: "",
          messages: { wet: "", recovery: "", fault: "" },
        },
        notificationRoles: DEFAULT_NOTIFICATION_ROLES.slice(),
        sirenRoles: [],
      },
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
      const settings = session.settings || {};
      state.draft.areaId = typeof settings.area_id === "string" ? settings.area_id : null;
      state.draft.selections = {};
      state.draft.confirmations = {};
      for (const selection of session.selections) {
        if (selection.candidate_id) state.draft.selections[selection.role] = selection.candidate_id;
        state.draft.confirmations[selection.role] = Boolean(selection.user_confirmed);
      }
      state.draft.notificationRoles = Array.isArray(settings.notification_target_roles)
        ? settings.notification_target_roles.slice()
        : DEFAULT_NOTIFICATION_ROLES.slice();
      state.draft.sirenRoles = Array.isArray(settings.siren_target_roles) ? settings.siren_target_roles.slice() : [];
      state.draft.settings.critical_sensor = Boolean(settings.critical_sensor);
      state.draft.settings.unavailable_grace_seconds = settings.unavailable_grace_seconds ?? 60;
      const repeat = settings.fault_repeat_interval_seconds;
      state.draft.settings.fault_repeat_interval_seconds = repeat === null || repeat === undefined ? "" : String(repeat);
      const messages = settings.messages && typeof settings.messages === "object" ? settings.messages : {};
      state.draft.settings.messages = {
        wet: messages.wet || "",
        recovery: messages.recovery || "",
        fault: messages.fault || "",
      };
      state.dirty = false;
    }

    function draftIsReady() {
      return Boolean(
        state.session &&
        !state.dirty &&
        state.session.validation_status === "CURRENT" &&
        state.session.activation_ready
      );
    }

    function roleLabel(role) {
      if (role === MOISTURE_SENSOR_ROLE) return t("wizard.water.role_moisture_sensor");
      if (role && role.startsWith(NOTIFICATION_ROLE_PREFIX)) return t("wizard.water.role_notification");
      if (role && role.startsWith(SIREN_ROLE_PREFIX)) return t("wizard.water.role_siren");
      return role || t("common.unknown");
    }

    function validationMessage(issue) {
      const path = Array.isArray(issue.path) && issue.path.length
        ? issue.path.join(".")
        : t("common.unknown");
      const parameters = {
        ...(issue.parameters || {}),
        field: path,
        role: roleLabel(issue.module_role || (issue.parameters && issue.parameters.role)),
      };
      return CI18N && typeof CI18N.has === "function" && CI18N.has(issue.message_key)
        ? t(issue.message_key, parameters)
        : t("wizard.validation_issue_fallback");
    }

    function validationDetails(issue) {
      const details = [];
      if (Array.isArray(issue.path) && issue.path.length) {
        details.push(t("wizard.validation_path", { path: issue.path.join(".") }));
      }
      if (
        issue.suggested_action &&
        CI18N &&
        typeof CI18N.has === "function" &&
        CI18N.has(`setup_action.${issue.suggested_action}`)
      ) {
        details.push(t(`setup_action.${issue.suggested_action}`));
      }
      return details.join(" ┬Ě ");
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
        const discoveredNotifications = rolesWithPrefix(recommendations, NOTIFICATION_ROLE_PREFIX);
        if (discoveredNotifications.length) state.draft.notificationRoles = discoveredNotifications;
        const discoveredSirens = rolesWithPrefix(recommendations, SIREN_ROLE_PREFIX);
        if (discoveredSirens.length) state.draft.sirenRoles = discoveredSirens;
        const existingDraftId = forceNewDraft ? null : storedDraftId();
        let session;
        if (existingDraftId) {
          session = await client.reopenDraft({ draft_id: existingDraftId, ...context });
        } else {
          session = await client.startDraft({
            draft_id: makeId("draft"),
            module_instance_id: "main-water-safety",
            created_at: context.captured_at,
            snapshot_id: context.snapshot_id,
            report_id: makeId("report"),
            settings: draftSettings(),
            selections: [],
          });
          storeDraftId(session.draft_id);
        }
        applySession(session);
        if (existingDraftId) state.step = STEP_COUNT;
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
      state.draft = {
        areaId: null,
        selections: {},
        confirmations: {},
        settings: {
          critical_sensor: false,
          unavailable_grace_seconds: 60,
          fault_repeat_interval_seconds: "",
          messages: { wet: "", recovery: "", fault: "" },
        },
        notificationRoles: DEFAULT_NOTIFICATION_ROLES.slice(),
        sirenRoles: [],
      };
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

    function updateSetting(key, value) {
      state.draft.settings[key] = value;
      state.dirty = true;
      render();
    }

    function updateMessage(key, value) {
      state.draft.settings.messages[key] = value;
      state.dirty = true;
      render();
    }

    function draftSettings() {
      const area = areas().find((item) => item.native_id === state.draft.areaId);
      const areaId = area && area.native_id ? area.native_id : (state.draft.areaId || "default-area");
      const areaName = areaId;
      const sensor = candidate(MOISTURE_SENSOR_ROLE, state.draft.selections[MOISTURE_SENSOR_ROLE]);
      const sensorId = sensor && (sensor.native_id || sensor.current_locator) ? (sensor.native_id || sensor.current_locator) : "moisture-sensor";
      const repeatRaw = state.draft.settings.fault_repeat_interval_seconds;
      const repeat = repeatRaw === "" || repeatRaw === null || repeatRaw === undefined
        ? null
        : Number(repeatRaw);
      const messages = {};
      for (const [key, value] of Object.entries(state.draft.settings.messages)) {
        if (value) messages[key] = value;
      }
      return {
        behavior_contract_version: 1,
        zone_id: areaId,
        zone_name: areaName,
        area_id: areaId,
        area_name: areaName,
        sensor_id: sensorId,
        critical_sensor: Boolean(state.draft.settings.critical_sensor),
        unavailable_grace_seconds: Number(state.draft.settings.unavailable_grace_seconds) || 60,
        fault_repeat_interval_seconds: Number.isFinite(repeat) ? repeat : null,
        notification_target_roles: state.draft.notificationRoles.slice(),
        siren_target_roles: state.draft.sirenRoles.filter((role) => state.draft.selections[role]).slice(),
        messages,
      };
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

    async function canonicalizeDraft() {
      let session = state.session;
      const savedBefore = state.dirty;
      if (savedBefore) session = await saveDraft();
      if (!session || (savedBefore && state.status === "error")) return;
      if (!session.activation_ready) return;
      if (!client.canonicalizeDraft) return;
      state.status = "saving";
      state.error = null;
      state.errorOperation = null;
      render();
      const createdAt = now();
      const validationReportId = session.validation_report_id || makeId("report");
      try {
        const canonicalized = await client.canonicalizeDraft({
          draft_id: session.draft_id,
          snapshot_id: state.snapshot.snapshot_id,
          created_at: createdAt,
          validation_report_id: validationReportId,
          configuration_id: makeId("configuration"),
          revision_id: makeId("revision"),
          revision: session.active_revision_id ? 2 : 1,
          actor: "user:setup_wizard",
          source: "setup_write_v1",
          change_kind: session.active_revision_id ? "UPDATE" : "CREATE",
          reason: "water_safety_wizard_activation",
          core_version: coreVersion,
          integration_version: integrationVersion,
          parent_revision_id: session.active_revision_id,
        });
        applySession(canonicalized);
        state.lastSavedAt = createdAt;
        state.status = "loaded";
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "canonicalize";
      }
      render();
    }

    async function activateDraft() {
      let session = state.session;
      if (!session || !session.canonical_revision_id || !client.activateDraft) return;
      state.status = "saving";
      state.error = null;
      state.errorOperation = null;
      render();
      const activatedAt = now();
      try {
        const activated = await client.activateDraft({
          draft_id: session.draft_id,
          canonical_revision_id: session.canonical_revision_id,
          snapshot_id: state.snapshot.snapshot_id,
          captured_at: activatedAt,
          report_id: makeId("report"),
          attempt_id: makeId("attempt"),
        });
        applySession(activated);
        state.lastSavedAt = activatedAt;
        state.status = "loaded";
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "activate";
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
        const existingDraftId = storedDraftId();
        return el("div", { class: "step" },
          el("h2", { class: "step__title" }, t("wizard.water.discovery_title")),
          el("p", { class: "step__lead" }, t("wizard.water.discovery_lead")),
          existingDraftId
            ? noteBox(t("wizard.resume_available", { draft: existingDraftId }), "info")
            : noteBox(t("wizard.not_discovered"), "neutral"),
          el("div", { class: "panel__actions" },
            el(
              "button",
              { class: "btn btn--primary", onclick: () => startDiscovery() },
              existingDraftId ? t("wizard.resume_draft") : t("wizard.start_discovery")
            )
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
        el("h2", { class: "step__title" }, t("wizard.water.discovery_title")),
        el("p", { class: "step__lead" }, t("wizard.water.discovery_lead")),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.snapshot")),
          el("div", { class: "kv-grid" },
            kvRow(t("wizard.provider"), snapshot.provider),
            kvRow(t("wizard.instance"), snapshot.provider_instance_id),
            kvRow(t("wizard.snapshot_id"), snapshot.snapshot_id),
            kvRow(t("wizard.captured_at"), formatTime(snapshot.captured_at)),
            kvRow(t("wizard.draft"), state.session.draft_id),
            kvRow(t("wizard.revision"), String(state.session.draft_revision))
          ),
          el("div", { class: "count-grid" },
            [[t("wizard.count_areas"), count(AREA_KIND)],
             [t("wizard.count_entities"), count("home_assistant.entity")]].map(([label, value]) =>
              el("div", { class: "count" },
                el("span", { class: "count__value" }, String(value)),
                el("span", { class: "count__label" }, label)
              )
            )
          )
        ),
        noteBox(t("wizard.discovery_note"), "info")
      );
    }

    function renderArea() {
      const discoveredAreas = areas();
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.water.area_title")),
        el("p", { class: "step__lead" }, t("wizard.water.area_lead")),
        discoveredAreas.length === 0
          ? noteBox(t("wizard.no_areas"), "warning")
          : el("div", { class: "candidate-list" }, discoveredAreas.map((area) => {
              const id = area.native_id;
              const selected = state.draft.areaId === id;
              return el("label", { class: `candidate ${selected ? "candidate--selected" : ""}` },
                el("span", { class: "candidate__head" },
                  el("input", { type: "radio", name: "water-setup-area", checked: selected, onchange: () => selectArea(id) }),
                  el("span", { class: "candidate__name" }, id || "Unknown area")
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
        })))
      );
    }

    function renderNotifications() {
      const roles = state.draft.notificationRoles.length
        ? state.draft.notificationRoles
        : rolesWithPrefix(state.recommendations, NOTIFICATION_ROLE_PREFIX);
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.water.notifications_title")),
        el("p", { class: "step__lead" }, t("wizard.water.notifications_lead")),
        roles.length
          ? roles.map((role) => renderRole(role, roleLabel(role), t("wizard.water.notifications_lead")))
          : noteBox(t("wizard.no_candidates"), "warning")
      );
    }

    function renderSirens() {
      const roles = state.draft.sirenRoles.length
        ? state.draft.sirenRoles
        : rolesWithPrefix(state.recommendations, SIREN_ROLE_PREFIX);
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.water.sirens_title")),
        el("p", { class: "step__lead" }, t("wizard.water.sirens_lead")),
        noteBox(t("wizard.water.sirens_lead"), "info"),
        roles.length
          ? roles.map((role) => renderRole(role, roleLabel(role), t("wizard.water.sirens_lead")))
          : noteBox(t("wizard.no_candidates"), "neutral")
      );
    }

    function renderSettings() {
      const settings = state.draft.settings;
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.water.settings_title")),
        el("p", { class: "step__lead" }, t("wizard.water.settings_lead")),
        el("div", { class: "panel" },
          el("label", { class: "settings-row" },
            el("input", {
              type: "checkbox",
              checked: Boolean(settings.critical_sensor),
              onchange: (e) => updateSetting("critical_sensor", Boolean(e.target && e.target.checked)),
            }),
            el("span", {}, t("wizard.water.critical_sensor"))
          ),
          el("label", { class: "settings-row" },
            el("span", {}, t("wizard.water.grace_seconds")),
            el("input", {
              type: "number",
              min: "0",
              value: String(settings.unavailable_grace_seconds),
              onchange: (e) => updateSetting("unavailable_grace_seconds", e.target && e.target.value),
            })
          ),
          el("label", { class: "settings-row" },
            el("span", {}, t("wizard.water.fault_repeat_seconds")),
            el("input", {
              type: "number",
              min: "1",
              value: String(settings.fault_repeat_interval_seconds),
              placeholder: t("common.none"),
              onchange: (e) => updateSetting("fault_repeat_interval_seconds", e.target && e.target.value),
            })
          ),
          el("label", { class: "settings-row" },
            el("span", {}, t("wizard.water.message_wet")),
            el("input", {
              type: "text",
              value: settings.messages.wet,
              onchange: (e) => updateMessage("wet", e.target && e.target.value),
            })
          ),
          el("label", { class: "settings-row" },
            el("span", {}, t("wizard.water.message_recovery")),
            el("input", {
              type: "text",
              value: settings.messages.recovery,
              onchange: (e) => updateMessage("recovery", e.target && e.target.value),
            })
          ),
          el("label", { class: "settings-row" },
            el("span", {}, t("wizard.water.message_fault")),
            el("input", {
              type: "text",
              value: settings.messages.fault,
              onchange: (e) => updateMessage("fault", e.target && e.target.value),
            })
          )
        )
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
      const reviewLoaded = state.status === "loaded";
      const issues = session.validation_issues || [];
      const blockingIssues = issues.filter((issue) => issue.severity === "ERROR");
      const warnings = issues.filter((issue) => issue.severity !== "ERROR");
      const ready = draftIsReady();
      const readinessMessage = state.dirty
        ? t("wizard.not_ready_unsaved")
        : session.validation_status !== "CURRENT"
          ? t("wizard.not_ready_validation", { status: session.validation_status })
          : ready
            ? t("wizard.ready_not_active")
            : t("wizard.not_ready_blocking", { count: session.blocking_issue_count });

      function issueList(group, severity) {
        if (!group.length) return null;
        return el("ul", { class: `validation-list validation-list--${severity}` }, group.map((issue) => validationItem({
          severity,
          code: issue.code,
          message: validationMessage(issue),
          details: validationDetails(issue),
        })));
      }

      const notificationRoles = state.draft.notificationRoles;
      const sirenRoles = state.draft.sirenRoles.filter((role) => state.draft.selections[role]);

      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.review_title")),
        el("p", { class: "step__lead" }, t("wizard.water.review_persisted_lead")),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.draft_review")),
          el("div", { class: "review-row" },
            el("span", { class: "review-row__label" }, t("wizard.zone")),
            state.draft.areaId || badge(t("wizard.not_selected"), "warning")
          ),
          reviewSelection(MOISTURE_SENSOR_ROLE, t("wizard.water.role_moisture_sensor")),
          notificationRoles.map((role) => reviewSelection(role, roleLabel(role))),
          sirenRoles.length
            ? sirenRoles.map((role) => reviewSelection(role, roleLabel(role)))
            : el("div", { class: "review-row" },
                el("span", { class: "review-row__label" }, t("wizard.water.role_siren")),
                badge(t("wizard.not_selected"), "neutral")
              ),
          state.dirty ? noteBox(t("wizard.unsaved_report"), "warning") : null
        ),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.validation_report")),
          el("div", { class: `readiness-summary readiness-summary--${ready ? "ready" : "not-ready"}` },
            badge(ready ? t("wizard.ready") : t("wizard.not_ready"), ready ? "positive" : "negative"),
            el("span", { class: "readiness-summary__message" }, readinessMessage)
          ),
          blockingIssues.length
            ? el("div", { class: "validation-group validation-group--blocking" },
                el("h4", { class: "validation-group__title" }, t("wizard.blocking_issues")),
                issueList(blockingIssues, "blocking")
              )
            : noteBox(t("wizard.no_blocking_issues"), ready ? "positive" : "neutral"),
          warnings.length
            ? el("div", { class: "validation-group validation-group--warning" },
                el("h4", { class: "validation-group__title" }, t("wizard.validation_warnings")),
                issueList(warnings, "warning")
              )
            : null,
          noteBox(t("wizard.validation_preparation"), "neutral")
        ),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.water.lifecycle_title")),
          el("p", { class: "step__lead" }, t("wizard.water.lifecycle_lead")),
          el("div", { class: "panel__actions panel__actions--stacked" },
            el("button", {
              class: "btn btn--secondary",
              disabled: !reviewLoaded || !state.session,
              onclick: saveDraft,
            }, state.status === "saving" && state.errorOperation !== "validate" ? t("wizard.saving") : t("wizard.save_later")),
            el("button", {
              class: "btn btn--secondary",
              disabled: !reviewLoaded || !state.session,
              onclick: validateDraft,
            }, t("wizard.validate_draft")),
            el("button", {
              class: "btn btn--secondary",
              disabled: !reviewLoaded || !state.session || !draftIsReady() || Boolean(state.session.canonical_revision_id),
              onclick: canonicalizeDraft,
            }, t("wizard.canonicalize_draft")),
            el("button", {
              class: "btn btn--primary",
              disabled: !reviewLoaded || !state.session || !state.session.canonical_revision_id || Boolean(state.session.active_revision_id),
              onclick: activateDraft,
            }, t("wizard.activate"))
          ),
          state.session && state.session.canonical_revision_id && !state.session.active_revision_id
            ? noteBox(t("wizard.water.canonicalized_not_active"), "info")
            : null,
          state.session && state.session.active_revision_id
            ? noteBox(t("wizard.water.activated_revision", { revision: state.session.active_revision_id }), "positive")
            : null
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
        badge(draftIsReady() ? t("wizard.ready") : t("wizard.not_ready"), draftIsReady() ? "positive" : "negative"),
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
        onclick: state.step < STEP_COUNT ? () => goToStep(state.step + 1) : validateDraft,
      }, state.step < STEP_COUNT ? t("wizard.continue") : t("wizard.validate_draft"));
      if (state.step === STEP_COUNT) {
        footer.replaceChildren(back, save);
      } else {
        footer.replaceChildren(back, save, next);
      }
    }

    function render() {
      renderStepper();
      let content;
      if (state.step === 1) content = renderDiscovery();
      else if (state.step === 2) content = renderArea();
      else if (state.step === 3) {
        content = el("div", { class: "step" },
          el("h2", { class: "step__title" }, t("wizard.water.sensor_title")),
          el("p", { class: "step__lead" }, t("wizard.water.sensor_lead")),
          renderRole(MOISTURE_SENSOR_ROLE, t("wizard.water.role_moisture_sensor"), t("wizard.water.sensor_lead"))
        );
      }
      else if (state.step === 4) content = renderNotifications();
      else if (state.step === 5) content = renderSirens();
      else if (state.step === 6) content = renderSettings();
      else content = renderReview();
      if (state.status === "error" && state.step !== 1) {
        panel.replaceChildren(
          el("div", { class: "state-panel state-panel--error" },
            el("p", { class: "state-panel__title" }, t("wizard.draft_unavailable")),
            el("p", { class: "state-panel__message" }, state.error && state.error.message ? state.error.message : "The setup request failed."),
            el("button", {
              class: "btn btn--secondary",
              onclick: state.errorOperation === "validate"
                ? validateDraft
                : state.errorOperation === "canonicalize"
                  ? canonicalizeDraft
                  : state.errorOperation === "activate"
                    ? activateDraft
                    : saveDraft,
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
      setEntryState(entryState) {
        state.entryState = entryState && typeof entryState === "object" ? entryState : null;
        render();
      },
      startDiscovery,
      startNewDraft,
      saveDraft,
      validateDraft,
      canonicalizeDraft,
      activateDraft,
      goToStep,
      render,
    };
    render();
    return api;
  }

  global.CA_WATER_WIZARD = {
    MOISTURE_SENSOR_ROLE,
    NOTIFICATION_ROLE_PREFIX,
    SIREN_ROLE_PREFIX,
    STEPS,
    candidateView,
    recommendationCandidates,
    rolesWithPrefix,
    createSetupWaterWizard,
  };
})(typeof window !== "undefined" ? window : globalThis);
