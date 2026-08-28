/*
 * Controlel setup wizard — canonical configuration v3 projection.
 *
 * Discovery and recommendations remain read-only Setup API v1 contracts.
 * Draft persistence, validation, canonicalization, and activation are the
 * same canonical-v3 lifecycle used by native Home Assistant Configure.
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
    { id: 4, key: "wizard.step_settings" },
    { id: 5, key: "wizard.step_review" },
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

  function candidateDomain(candidate) {
    const evidence = candidate && candidate.evidence;
    if (evidence && typeof evidence.domain === "string") return evidence.domain;
    const locator = candidate && candidate.current_locator;
    return typeof locator === "string" && locator.includes(".") ? locator.split(".", 1)[0] : null;
  }

  function isWizardCandidateCompatible(role, candidate) {
    if (!candidate) return false;
    if (candidate.identity_quality !== "STABLE" || !candidate.native_id) return false;
    const locator = candidate.current_locator || "";
    const objectId = locator.includes(".") ? locator.slice(locator.indexOf(".") + 1) : "";
    if ((candidate.evidence && candidate.evidence.platform === "controlel") || objectId.startsWith("controlel_")) {
      return false;
    }
    const capabilities = candidate.capabilities || [];
    if (role === PRIMARY_TEMPERATURE_ROLE) {
      return candidateDomain(candidate) === "sensor" && capabilities.includes("measurement.temperature");
    }
    if (role === SOURCE_ENABLE_TARGET_ROLE || role === SOURCE_DISABLE_TARGET_ROLE) {
      return candidateDomain(candidate) === "switch" && capabilities.includes("command.enable_disable");
    }
    return false;
  }

  function rankCandidates(candidates, preferredAreaId) {
    const confidenceRank = { HIGH: 0, MEDIUM: 1, LOW: 2 };
    const identityRank = { STABLE: 0, RECOVERABLE: 1, EPHEMERAL: 2 };
    return candidates.slice().sort((left, right) => {
      const leftArea = preferredAreaId && left.area_id !== preferredAreaId ? 1 : 0;
      const rightArea = preferredAreaId && right.area_id !== preferredAreaId ? 1 : 0;
      if (leftArea !== rightArea) return leftArea - rightArea;
      const confidence = (confidenceRank[left.confidence] ?? 3) - (confidenceRank[right.confidence] ?? 3);
      if (confidence) return confidence;
      const identity = (identityRank[left.identity_quality] ?? 3) - (identityRank[right.identity_quality] ?? 3);
      if (identity) return identity;
      return String(left.current_locator || left.native_id || "").localeCompare(
        String(right.current_locator || right.native_id || "")
      );
    });
  }

  function deepCopy(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
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
    const actor = typeof opts.actor === "string" && opts.actor ? opts.actor : "home_assistant:admin";
    const confirmAction = typeof opts.confirm === "function"
      ? opts.confirm
      : (message) => typeof global.confirm === "function" && global.confirm(message);
    const storage = opts.storage || null;
    const storageKey = `controlel.configuration.draft.v3.${opts.configEntryId || "unknown"}`;
    const state = {
      step: 1,
      status: "idle",
      entryState: null,
      error: null,
      errorOperation: null,
      snapshot: null,
      recommendations: [],
      configurationDefaults: { settings: {}, simple_switch: {}, core_version: null, integration_version: null },
      session: null,
      validation: null,
      candidateRevision: null,
      activation: null,
      dirty: false,
      lastSavedAt: null,
      expandedRoles: {},
      draft: {
        areaId: null, selections: {}, confirmations: {}, settings: {}, areaTouched: false,
        touchedRoles: {}, persistedReferences: {},
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

    function matchingCandidate(role, reference) {
      if (!reference) return null;
      return recommendationCandidates(recommendation(role)).find((item) =>
        (reference.native_id && item.native_id === reference.native_id) ||
        (!reference.native_id && reference.current_locator && item.current_locator === reference.current_locator)
      ) || null;
    }

    function applySession(session) {
      const zone = session.heating.zones[0];
      const source = session.heating.heat_sources[0];
      const globalConfiguration = session.heating.global;
      const protection = source.protection;
      state.session = session;
      state.validation = null;
      state.candidateRevision = null;
      state.activation = null;
      state.draft.settings = {
        target_temperature_celsius: zone.demand_policy.target_temperature_celsius,
        primary_measurement_max_age_seconds: zone.demand_policy.primary_measurement_max_age_seconds,
        heating_turn_on_differential_celsius: zone.demand_policy.heating_turn_on_differential_celsius,
        heating_turn_off_differential_celsius: zone.demand_policy.heating_turn_off_differential_celsius,
        heat_demand_confirmation_seconds: zone.demand_policy.heat_demand_confirmation_seconds,
        maximum_future_skew_seconds: globalConfiguration.maximum_future_skew_seconds,
        indeterminate_grace_period_seconds: protection.indeterminate_grace_period_seconds,
        minimum_heating_on_seconds: protection.minimum_heating_on_seconds,
        minimum_heating_off_seconds: protection.minimum_heating_off_seconds,
      };
      const areaReference = zone.topology.area_reference;
      state.draft.areaId = areaReference ? areaReference.native_id : null;
      state.draft.selections = {};
      state.draft.confirmations = {};
      state.draft.areaTouched = false;
      state.draft.touchedRoles = {};
      const references = {
        [PRIMARY_TEMPERATURE_ROLE]: zone.primary_temperature_sensor.provider_reference,
        [SOURCE_ENABLE_TARGET_ROLE]: source.command_strategy.enable_permission.command_target_reference,
        [SOURCE_DISABLE_TARGET_ROLE]: source.command_strategy.disable_permission.command_target_reference,
      };
      state.draft.persistedReferences = {
        area: areaReference,
        ...references,
      };
      for (const [role, reference] of Object.entries(references)) {
        const matched = matchingCandidate(role, reference);
        if (matched) state.draft.selections[role] = matched.candidate_id;
        state.draft.confirmations[role] = Boolean(matched);
      }
      state.dirty = false;
      state.expandedRoles = {};
    }

    function draftIsReady() {
      return Boolean(
        state.session &&
        !state.dirty &&
        state.validation &&
        state.validation.draft_id === state.session.draft_id &&
        state.validation.draft_revision === state.session.revision &&
        state.validation.activation_ready
      );
    }

    function roleLabel(role) {
      const key = {
        [PRIMARY_TEMPERATURE_ROLE]: "wizard.role_sensor",
        [SOURCE_ENABLE_TARGET_ROLE]: "wizard.source_enable_target",
        [SOURCE_DISABLE_TARGET_ROLE]: "wizard.source_disable_target",
        "heating.source.reported_state": "wizard.reported_source_state",
        "heating.heat_delivery.actuator": "wizard.heat_delivery_actuator",
      }[role];
      return key ? t(key) : role || t("common.unknown");
    }

    function requestContext() {
      return { snapshot_id: makeId("snapshot"), captured_at: now() };
    }

    function resetIntent() {
      state.session = null;
      state.validation = null;
      state.candidateRevision = null;
      state.activation = null;
      state.draft = {
        areaId: null,
        selections: {},
        confirmations: {},
        settings: { ...state.configurationDefaults.settings },
        areaTouched: false,
        touchedRoles: {},
        persistedReferences: {},
      };
      state.dirty = false;
    }

    function earliestCorrectionStep() {
      const persisted = state.draft.persistedReferences;
      if (state.session) {
        if (persisted.area && !discoveredObject(persisted.area)) return 2;
      } else if (!state.draft.areaId || !areas().some((item) => item.native_id === state.draft.areaId)) {
        return 2;
      }
      const requiredRoles = [PRIMARY_TEMPERATURE_ROLE, SOURCE_ENABLE_TARGET_ROLE, SOURCE_DISABLE_TARGET_ROLE];
      for (const role of requiredRoles) {
        if (!state.draft.touchedRoles[role] && state.session && providerReference(persisted[role])) continue;
        const selected = candidate(role, state.draft.selections[role]);
        if (!isWizardCandidateCompatible(role, selected) || !state.draft.confirmations[role]) return 3;
      }
      return 5;
    }

    async function startDiscovery({ forceNewDraft = false } = {}) {
      state.status = "loading";
      state.error = null;
      state.errorOperation = null;
      render();
      const context = requestContext();
      try {
        const [snapshot, recommendations, configurationDefaults, drafts] = await Promise.all([
          client.discover(context),
          client.recommendations(context),
          client.defaults(),
          client.listDrafts(),
        ]);
        state.snapshot = snapshot;
        state.recommendations = recommendations;
        state.configurationDefaults = configurationDefaults;
        resetIntent();

        let session = null;
        const localDraftId = forceNewDraft ? null : storedDraftId();
        const backendDraftIds = forceNewDraft ? [] : drafts.slice().sort((left, right) =>
          String(right.updated_at).localeCompare(String(left.updated_at))
        ).map((draft) => draft.draft_id);
        const resumeDraftIds = [localDraftId, ...backendDraftIds]
          .filter((draftId, index, all) => draftId && all.indexOf(draftId) === index);
        for (const draftId of resumeDraftIds) {
          try {
            session = await client.reopenDraft({ draft_id: draftId });
            break;
          } catch (error) {
            const recoverableCodes = new Set(["not_found", "invalid_format", "setup_storage_integrity"]);
            if (!recoverableCodes.has(error && error.code)) throw error;
            if (draftId === localDraftId) clearStoredDraftId();
          }
        }
        if (!session) {
          try {
            const active = await client.readActive(context);
            session = await client.editDraft({
              draft_id: makeId("wizard-edit-draft"),
              created_at: context.captured_at,
              expected_active_generation: active.active_reference.generation,
            });
          } catch (error) {
            if (!new Set(["not_found", "setup_conflict"]).has(error && error.code)) throw error;
          }
        }
        if (session) {
          applySession(session);
          storeDraftId(session.draft_id);
          state.step = earliestCorrectionStep();
        }
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
      resetIntent();
      state.step = 1;
      return startDiscovery({ forceNewDraft: true });
    }

    async function deleteDraft() {
      if (!state.session || state.status !== "loaded") return null;
      if (!confirmAction(t("wizard.delete_draft_confirm"))) return null;
      state.status = "saving";
      state.error = null;
      state.errorOperation = null;
      render();
      try {
        const abandoned = await client.abandonDraft({
          draft_id: state.session.draft_id,
          expected_revision: state.session.revision,
        });
        clearStoredDraftId();
        resetIntent();
        state.step = 1;
        await startDiscovery({ forceNewDraft: true });
        return abandoned;
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "delete";
        render();
        return null;
      }
    }

    function selectArea(areaId) {
      state.draft.areaId = areaId;
      state.draft.areaTouched = true;
      state.expandedRoles = {};
      state.dirty = true;
      state.validation = null;
      state.candidateRevision = null;
      render();
    }

    function sameCandidateIdentity(left, right) {
      if (!left || !right) return false;
      if (left.native_id && right.native_id) return left.native_id === right.native_id;
      return Boolean(left.current_locator && left.current_locator === right.current_locator);
    }

    function pairedSourceSelection(role, selected) {
      const otherRole = role === SOURCE_ENABLE_TARGET_ROLE
        ? SOURCE_DISABLE_TARGET_ROLE
        : SOURCE_ENABLE_TARGET_ROLE;
      return recommendationCandidates(recommendation(otherRole)).find(
        (item) => isWizardCandidateCompatible(otherRole, item) && sameCandidateIdentity(selected, item)
      ) || null;
    }

    function selectCandidate(role, candidateId) {
      state.draft.selections[role] = candidateId;
      state.draft.confirmations[role] = false;
      state.draft.touchedRoles[role] = true;
      if (role === SOURCE_ENABLE_TARGET_ROLE || role === SOURCE_DISABLE_TARGET_ROLE) {
        const selected = candidate(role, candidateId);
        const paired = pairedSourceSelection(role, selected);
        if (paired) {
          const otherRole = role === SOURCE_ENABLE_TARGET_ROLE
            ? SOURCE_DISABLE_TARGET_ROLE
            : SOURCE_ENABLE_TARGET_ROLE;
          state.draft.selections[otherRole] = paired.candidate_id;
          state.draft.confirmations[otherRole] = false;
          state.draft.touchedRoles[otherRole] = true;
        }
      }
      state.dirty = true;
      state.validation = null;
      state.candidateRevision = null;
      render();
    }

    function confirmCandidate(role, value) {
      state.draft.confirmations[role] = Boolean(value);
      state.draft.touchedRoles[role] = true;
      if (role === SOURCE_ENABLE_TARGET_ROLE || role === SOURCE_DISABLE_TARGET_ROLE) {
        const selected = candidate(role, state.draft.selections[role]);
        const paired = pairedSourceSelection(role, selected);
        if (paired) {
          const otherRole = role === SOURCE_ENABLE_TARGET_ROLE
            ? SOURCE_DISABLE_TARGET_ROLE
            : SOURCE_ENABLE_TARGET_ROLE;
          if (state.draft.selections[otherRole] === paired.candidate_id) {
            state.draft.confirmations[otherRole] = Boolean(value);
            state.draft.touchedRoles[otherRole] = true;
          }
        }
      }
      state.dirty = true;
      state.validation = null;
      state.candidateRevision = null;
      render();
    }

    function discoveredObject(referenceLike) {
      if (!referenceLike || !state.snapshot) return null;
      return state.snapshot.objects.find((item) => {
        if (referenceLike.object_kind && item.object_kind !== referenceLike.object_kind) return false;
        if (referenceLike.native_id) return item.native_id === referenceLike.native_id;
        return Boolean(referenceLike.current_locator && item.current_locator === referenceLike.current_locator);
      }) || null;
    }

    function providerReference(referenceLike) {
      const item = discoveredObject(referenceLike);
      if (!item || item.identity_quality !== "STABLE" || !item.native_id) return null;
      return {
        provider: state.snapshot.provider,
        provider_instance_id: state.snapshot.provider_instance_id,
        object_kind: item.object_kind,
        native_id: item.native_id,
        identity_quality: item.identity_quality,
        current_locator: item.current_locator,
        device_registry_id: item.device_registry_id,
        area_id: item.area_id,
        floor_id: item.floor_id,
        recovery_evidence: {},
      };
    }

    function selectedReference(role) {
      return providerReference(candidate(role, state.draft.selections[role]));
    }

    function greenfieldBindings() {
      const area = areas().find((item) => item.native_id === state.draft.areaId);
      const sensor = candidate(PRIMARY_TEMPERATURE_ROLE, state.draft.selections[PRIMARY_TEMPERATURE_ROLE]);
      const enable = candidate(SOURCE_ENABLE_TARGET_ROLE, state.draft.selections[SOURCE_ENABLE_TARGET_ROLE]);
      const disable = candidate(SOURCE_DISABLE_TARGET_ROLE, state.draft.selections[SOURCE_DISABLE_TARGET_ROLE]);
      const areaReference = providerReference(area);
      const sensorReference = selectedReference(PRIMARY_TEMPERATURE_ROLE);
      const enableReference = selectedReference(SOURCE_ENABLE_TARGET_ROLE);
      const disableReference = selectedReference(SOURCE_DISABLE_TARGET_ROLE);
      if (
        !areaReference || !sensorReference || !enableReference || !disableReference ||
        !sameCandidateIdentity(enable, disable) ||
        !state.draft.confirmations[PRIMARY_TEMPERATURE_ROLE] ||
        !state.draft.confirmations[SOURCE_ENABLE_TARGET_ROLE] ||
        !state.draft.confirmations[SOURCE_DISABLE_TARGET_ROLE]
      ) return null;
      return {
        zone_display_name: area.current_locator || area.native_id,
        primary_sensor_display_name: sensor.current_locator || sensor.native_id,
        topology: { area_reference: areaReference, floor_reference: null },
        primary_temperature_sensor_reference: sensorReference,
        heat_source_display_name: enable.current_locator || enable.native_id,
        heat_source_reference: enableReference,
        command_strategy: {
          mode: "simple",
          enable_permission: { domain: "switch", service: "turn_on", command_target_reference: enableReference },
          disable_permission: { domain: "switch", service: "turn_off", command_target_reference: disableReference },
        },
        observations: { reported_actuator_state_reference: enableReference, physical_operation_reference: null },
      };
    }

    function configurationScopes(session) {
      const scopes = {
        heating: deepCopy(session.heating),
        diagnostics: deepCopy(session.diagnostics),
        notifications: deepCopy(session.notifications),
      };
      const zone = scopes.heating.zones[0];
      const source = scopes.heating.heat_sources[0];
      const settings = state.draft.settings;
      zone.demand_policy.target_temperature_celsius = settings.target_temperature_celsius;
      zone.demand_policy.primary_measurement_max_age_seconds = settings.primary_measurement_max_age_seconds;
      zone.demand_policy.heating_turn_on_differential_celsius = settings.heating_turn_on_differential_celsius;
      zone.demand_policy.heating_turn_off_differential_celsius = settings.heating_turn_off_differential_celsius;
      zone.demand_policy.heat_demand_confirmation_seconds = settings.heat_demand_confirmation_seconds;
      scopes.heating.global.maximum_future_skew_seconds = settings.maximum_future_skew_seconds;
      source.protection.indeterminate_grace_period_seconds = settings.indeterminate_grace_period_seconds;
      source.protection.minimum_heating_on_seconds = settings.minimum_heating_on_seconds;
      source.protection.minimum_heating_off_seconds = settings.minimum_heating_off_seconds;
      if (state.draft.areaTouched) {
        zone.topology.area_reference = providerReference(
          areas().find((item) => item.native_id === state.draft.areaId)
        );
      }
      if (state.draft.touchedRoles[PRIMARY_TEMPERATURE_ROLE]) {
        const reference = selectedReference(PRIMARY_TEMPERATURE_ROLE);
        if (!reference || !state.draft.confirmations[PRIMARY_TEMPERATURE_ROLE]) throw new Error(t("wizard.complete_before_save"));
        zone.primary_temperature_sensor.provider_reference = reference;
        zone.primary_temperature_sensor.display_name = reference.current_locator || reference.native_id;
      }
      if (state.draft.touchedRoles[SOURCE_ENABLE_TARGET_ROLE] || state.draft.touchedRoles[SOURCE_DISABLE_TARGET_ROLE]) {
        const enable = candidate(SOURCE_ENABLE_TARGET_ROLE, state.draft.selections[SOURCE_ENABLE_TARGET_ROLE]);
        const disable = candidate(SOURCE_DISABLE_TARGET_ROLE, state.draft.selections[SOURCE_DISABLE_TARGET_ROLE]);
        const enableReference = selectedReference(SOURCE_ENABLE_TARGET_ROLE);
        const disableReference = selectedReference(SOURCE_DISABLE_TARGET_ROLE);
        if (
          !enableReference || !disableReference || !sameCandidateIdentity(enable, disable) ||
          !state.draft.confirmations[SOURCE_ENABLE_TARGET_ROLE] ||
          !state.draft.confirmations[SOURCE_DISABLE_TARGET_ROLE]
        ) throw new Error(t("wizard.complete_before_save"));
        source.display_name = enableReference.current_locator || enableReference.native_id;
        source.provider_reference = enableReference;
        source.command_strategy = {
          mode: "simple",
          enable_permission: { domain: "switch", service: "turn_on", command_target_reference: enableReference },
          disable_permission: { domain: "switch", service: "turn_off", command_target_reference: disableReference },
        };
        source.observations.reported_actuator_state_reference = enableReference;
      }
      return scopes;
    }

    function setNumericSetting(name, rawValue) {
      const value = Number(rawValue);
      if (!Number.isFinite(value)) return;
      state.draft.settings[name] = value;
      state.dirty = true;
      state.validation = null;
      state.candidateRevision = null;
      renderDraftStatus();
    }

    async function saveDraft() {
      if (state.status === "saving") return null;
      state.status = "saving";
      state.error = null;
      state.errorOperation = null;
      render();
      const updatedAt = now();
      try {
        let base = state.session;
        const desiredSettings = { ...state.draft.settings };
        if (!base) {
          const bindings = greenfieldBindings();
          if (!bindings) {
            state.step = earliestCorrectionStep();
            state.status = "loaded";
            render();
            return null;
          }
          base = await client.startDraft({
            draft_id: makeId("wizard-greenfield-draft"),
            created_at: updatedAt,
            snapshot_id: state.snapshot.snapshot_id,
            bindings,
          });
          storeDraftId(base.draft_id);
          applySession(base);
          state.draft.settings = desiredSettings;
        }
        const session = await client.updateDraft({
          draft_id: base.draft_id,
          expected_revision: base.revision,
          updated_at: updatedAt,
          configuration_scopes: configurationScopes(base),
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
        state.validation = validated;
        state.candidateRevision = null;
        state.status = "loaded";
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "validate";
      }
      render();
    }

    async function canonicalizeDraft() {
      if (!draftIsReady() || state.status === "saving") return null;
      state.status = "saving";
      state.error = null;
      state.errorOperation = null;
      render();
      const createdAt = now();
      try {
        const revision = await client.canonicalizeDraft({
          draft_id: state.session.draft_id,
          validation_report_id: state.validation.report_id,
          revision_id: makeId("wizard-canonical-v3"),
          snapshot_id: state.snapshot.snapshot_id,
          created_at: createdAt,
          actor,
          source: "controlel_setup_wizard",
          change_kind: state.session.lineage.authoring_origin === "canonical_v2_conversion"
            ? "MIGRATE"
            : state.session.base_active_revision_id ? "UPDATE" : "CREATE",
          reason: "guided_setup_wizard",
          core_version: state.configurationDefaults.core_version,
          integration_version: state.configurationDefaults.integration_version,
        });
        state.candidateRevision = revision;
        state.status = "loaded";
        render();
        return revision;
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "canonicalize";
        render();
        return null;
      }
    }

    async function activateRevision() {
      if (!state.candidateRevision || state.status === "saving") return null;
      state.status = "saving";
      state.error = null;
      state.errorOperation = null;
      render();
      try {
        const activation = await client.activateRevision({
          revision_id: state.candidateRevision.revision_id,
          semantic_configuration_fingerprint: state.candidateRevision.semantic_configuration_fingerprint,
          expected_active_revision_id: state.session.base_active_revision_id,
          expected_active_generation: state.session.base_active_generation,
          attempt_id: makeId("wizard-activation"),
        });
        state.activation = activation;
        clearStoredDraftId();
        state.status = "loaded";
        render();
        return activation;
      } catch (error) {
        state.status = "error";
        state.error = error;
        state.errorOperation = "activate";
        render();
        return null;
      }
    }

    function formatTime(value) {
      if (!value) return "Unknown";
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
    }

    function goToStep(step) {
      if (state.status === "error" && state.session) {
        state.status = "loaded";
        state.error = null;
        state.errorOperation = null;
      }
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
        const entry = state.entryState;
        const readiness = entry && entry.status === "loaded" ? entry.readiness : null;
        let entryNote = null;
        if (readiness) {
          const messageKey = {
            ready: "wizard.entry_ready",
            incomplete: "wizard.entry_incomplete",
            invalid: "wizard.entry_invalid",
          }[readiness.state] || "wizard.entry_unknown";
          const tone = readiness.state === "ready"
            ? "positive"
            : readiness.state === "invalid"
              ? "negative"
              : readiness.state === "incomplete"
                ? "warning"
                : "neutral";
          entryNote = el("div", { class: "panel" },
            el("h3", { class: "panel__title" }, t("wizard.setup_entry")),
            el("div", { class: "section__badges" },
              badge(
                readiness.state === "ready"
                  ? t("wizard.ready")
                  : readiness.state === "unknown"
                    ? t("common.unknown")
                    : t("wizard.not_ready"),
                readiness.state === "ready" ? "positive" : readiness.state === "unknown" ? "neutral" : "warning"
              ),
              readiness.reason_code ? badge(readiness.reason_code, "neutral") : null
            ),
            noteBox(t(messageKey), tone)
          );
        } else if (entry && entry.status === "error") {
          entryNote = noteBox(
            t("wizard.entry_unavailable", {
              message: entry.error && entry.error.message ? entry.error.message : t("common.request_failed"),
            }),
            "warning"
          );
        }
        return el("div", { class: "step" },
          el("h2", { class: "step__title" }, t("wizard.discovery_title")),
          el("p", { class: "step__lead" }, t("wizard.discovery_lead")),
          entryNote,
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
            kvRow(t("wizard.draft"), state.session ? state.session.draft_id : t("wizard.not_saved")),
            kvRow(t("wizard.revision"), state.session ? String(state.session.revision) : t("common.unknown"))
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
      const allCandidates = rankCandidates(
        recommendationCandidates(item).filter((entry) => isWizardCandidateCompatible(role, entry)),
        state.draft.areaId
      );
      const selectedId = state.draft.selections[role];
      const recommendedId = allCandidates.length ? allCandidates[0].candidate_id : null;
      const selected = allCandidates.find((entry) => entry.candidate_id === selectedId) || null;
      const areaCandidates = state.draft.areaId
        ? allCandidates.filter((entry) => entry.area_id === state.draft.areaId)
        : allCandidates;
      let candidates = state.expandedRoles[role] ? allCandidates : areaCandidates.slice(0, 3);
      if (selected && !candidates.some((entry) => entry.candidate_id === selected.candidate_id)) {
        candidates = [selected, ...candidates.slice(0, 2)];
      }
      if (!item || allCandidates.length === 0) {
        return el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, heading),
          noteBox(t("wizard.no_candidates"), "warning")
        );
      }
      return el("div", { class: "panel" },
        el("h3", { class: "panel__title" }, heading),
        el("p", { class: "panel__lead" }, lead),
        candidates.length
          ? el("div", { class: "candidate-list" }, candidates.map((entry) => candidateCard({
              candidate: candidateView(entry),
              isRecommended: entry.candidate_id === recommendedId,
              selected: selectedId === entry.candidate_id,
              onSelect: (id) => selectCandidate(role, id),
              confirmed: Boolean(state.draft.confirmations[role]),
              onConfirm: item.explicit_confirmation_required ? (value) => confirmCandidate(role, value) : null,
              roleLabel: heading,
            })))
          : noteBox(t("wizard.no_candidates_in_area"), "warning"),
        allCandidates.length > candidates.length
          ? el("button", {
              class: "btn btn--link candidate-list__more",
              onclick: () => {
                state.expandedRoles[role] = true;
                render();
              },
            }, t("wizard.show_more_candidates", { count: allCandidates.length - candidates.length }))
          : state.expandedRoles[role] && allCandidates.length > Math.min(3, areaCandidates.length)
            ? el("button", {
                class: "btn btn--link candidate-list__more",
                onclick: () => {
                  state.expandedRoles[role] = false;
                  render();
                },
              }, t("wizard.show_fewer_candidates"))
            : null,
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
        renderRole(SOURCE_ENABLE_TARGET_ROLE, t("wizard.role_heat_source"), t("wizard.simple_switch_lead"))
      );
    }

    function numericSetting(name, label, { min = 0, step = "any", unit = "" } = {}) {
      const value = state.draft.settings[name];
      return el("label", { class: "settings-field" },
        el("span", { class: "settings-field__label" }, label),
        el("span", { class: "settings-field__control" },
          el("input", {
            class: "settings-field__input",
            type: "number",
            min,
            step,
            value,
            oninput: (event) => setNumericSetting(name, event.target.value),
          }),
          unit ? el("span", { class: "settings-field__unit" }, unit) : null
        )
      );
    }

    function renderSettings() {
      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.settings_title")),
        el("p", { class: "step__lead" }, t("wizard.settings_lead")),
        noteBox(t("wizard.settings_defaults_note"), "info"),
        el("div", { class: "panel settings-panel" },
          el("div", { class: "settings-grid" },
            numericSetting("target_temperature_celsius", t("wizard.target_temperature"), { step: "0.1", unit: "°C" }),
            numericSetting("primary_measurement_max_age_seconds", t("wizard.measurement_max_age"), { min: 1, step: "1", unit: t("wizard.seconds") }),
            numericSetting("maximum_future_skew_seconds", t("wizard.maximum_future_skew"), { step: "1", unit: t("wizard.seconds") }),
            numericSetting("indeterminate_grace_period_seconds", t("wizard.indeterminate_grace"), { step: "1", unit: t("wizard.seconds") })
          ),
          el("details", { class: "settings-advanced" },
            el("summary", { class: "settings-advanced__summary" }, t("wizard.advanced_control_settings")),
            el("p", { class: "panel__lead" }, t("wizard.advanced_control_lead")),
            el("div", { class: "settings-grid" },
              numericSetting("heating_turn_on_differential_celsius", t("wizard.turn_on_differential"), { step: "0.1", unit: "°C" }),
              numericSetting("heating_turn_off_differential_celsius", t("wizard.turn_off_differential"), { step: "0.1", unit: "°C" }),
              numericSetting("heat_demand_confirmation_seconds", t("wizard.demand_confirmation"), { step: "1", unit: t("wizard.seconds") }),
              numericSetting("minimum_heating_on_seconds", t("wizard.minimum_on_time"), { step: "1", unit: t("wizard.seconds") }),
              numericSetting("minimum_heating_off_seconds", t("wizard.minimum_off_time"), { step: "1", unit: t("wizard.seconds") })
            )
          )
        )
      );
    }

    function reviewSelection(role, label) {
      const selected = candidate(role, state.draft.selections[role]);
      const persisted = state.draft.persistedReferences[role];
      const displayed = selected || (persisted && discoveredObject(persisted) ? persisted : null);
      return el("div", { class: `review-row ${displayed ? "" : "review-row--missing"}` },
        el("span", { class: "review-row__label" }, label),
        displayed
          ? el("span", { class: "review-row__value" }, displayed.current_locator || displayed.native_id || "Unknown")
          : badge(t("wizard.not_selected"), "warning"),
        selected
          ? badge(state.draft.confirmations[role] ? t("wizard.confirmed") : t("wizard.not_confirmed"), state.draft.confirmations[role] ? "positive" : "negative")
          : displayed ? badge(t("wizard.persisted"), "info") : null
      );
    }

    function renderReview() {
      const session = state.session;
      const issues = state.validation ? state.validation.issue_codes : [];
      const ready = draftIsReady();
      const readinessMessage = !session
        ? t("wizard.not_ready_not_saved")
        : state.dirty
        ? t("wizard.not_ready_unsaved")
        : !state.validation
          ? t("wizard.not_ready_validation", { status: t("wizard.validation_status_not_validated") })
          : ready
            ? t("wizard.ready_not_active")
            : t("wizard.not_ready_blocking", { count: issues.length });

      return el("div", { class: "step" },
        el("h2", { class: "step__title" }, t("wizard.review_title")),
        el("p", { class: "step__lead" }, t("wizard.review_persisted_lead")),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.draft_review")),
          el("div", { class: "review-row" },
            el("span", { class: "review-row__label" }, t("wizard.zone")),
            state.draft.areaId || (session ? t("common.none") : badge(t("wizard.not_selected"), "warning"))
          ),
          reviewSelection(PRIMARY_TEMPERATURE_ROLE, t("wizard.role_sensor")),
          reviewSelection(SOURCE_ENABLE_TARGET_ROLE, t("wizard.source_enable_target")),
          reviewSelection(SOURCE_DISABLE_TARGET_ROLE, t("wizard.source_disable_target")),
          el("div", { class: "review-row" },
            el("span", { class: "review-row__label" }, t("wizard.target_temperature")),
            `${state.draft.settings.target_temperature_celsius} °C`
          ),
          el("div", { class: "review-row" },
            el("span", { class: "review-row__label" }, t("wizard.required_timing_settings")),
            t("wizard.required_timing_summary", {
              age: state.draft.settings.primary_measurement_max_age_seconds,
              skew: state.draft.settings.maximum_future_skew_seconds,
              grace: state.draft.settings.indeterminate_grace_period_seconds,
            })
          ),
          state.dirty ? noteBox(t("wizard.unsaved_report"), "warning") : null,
          !session ? noteBox(t("wizard.complete_before_save"), "warning") : null
        ),
        el("div", { class: "panel" },
          el("h3", { class: "panel__title" }, t("wizard.validation_report")),
          el("div", { class: `readiness-summary readiness-summary--${ready ? "ready" : "not-ready"}` },
            badge(ready ? t("wizard.ready") : t("wizard.not_ready"), ready ? "positive" : "negative"),
            el("span", { class: "readiness-summary__message" }, readinessMessage)
          ),
          el("div", { class: "section__badges" },
            badge(
              state.validation ? t("wizard.validation_status_current") : t("wizard.validation_status_not_validated"),
              state.validation ? "info" : "warning"
            ),
            badge(t("wizard.blocking_count", { count: issues.length }), issues.length ? "negative" : "positive")
          ),
          issues.length
            ? el("div", { class: "validation-group validation-group--blocking" },
                el("h4", { class: "validation-group__title" }, t("wizard.blocking_issues")),
                el("ul", { class: "validation-list validation-list--blocking" }, issues.map((code) =>
                  validationItem({ severity: "blocking", code, message: code, details: "" })
                ))
              )
            : noteBox(t("wizard.no_blocking_issues"), ready ? "positive" : "neutral"),
          noteBox(t("wizard.validation_preparation"), "neutral"),
          state.candidateRevision
            ? noteBox(t("wizard.canonicalized_not_active", { revision: state.candidateRevision.revision_id }), "positive")
            : null,
          state.activation ? noteBox(t("wizard.activation_complete"), "positive") : null
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
        badge(t("wizard.canonical_v3_draft"), "info"),
        el("span", { class: "draft-status__text" },
          t("wizard.revision_status", {
            revision: state.session.revision,
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
        class: "btn btn--secondary btn--back",
        disabled: state.step === 1 || !loaded,
        onclick: () => goToStep(state.step - 1),
      }, t("wizard.back"));
      const save = el("button", {
        class: "btn btn--secondary",
        disabled: !loaded,
        onclick: saveDraft,
      }, state.status === "saving" ? t("wizard.saving") : t("wizard.save_later"));
      const remove = el("button", {
        class: "btn btn--danger",
        disabled: !loaded || !state.session,
        onclick: deleteDraft,
      }, t("wizard.delete_draft"));
      const next = el("button", {
        class: "btn btn--primary",
        disabled: !loaded,
        onclick: state.step < 5 ? () => goToStep(state.step + 1) : validateDraft,
      }, state.step < 5 ? t("wizard.continue") : t("wizard.validate_draft"));
      const canonicalize = el("button", {
        class: "btn btn--secondary",
        disabled: !loaded || !draftIsReady() || Boolean(state.candidateRevision),
        onclick: canonicalizeDraft,
      }, t("wizard.canonicalize"));
      const activate = el("button", {
        class: "btn btn--primary",
        disabled: !loaded || !state.candidateRevision || Boolean(state.activation),
        onclick: activateRevision,
      }, t("wizard.activate"));
      footer.replaceChildren(
        back,
        remove,
        save,
        state.step === 5 && state.candidateRevision ? activate : state.step === 5 && draftIsReady() ? canonicalize : next
      );
    }

    function render() {
      renderStepper();
      let content;
      if (state.step === 1) content = renderDiscovery();
      else if (state.step === 2) content = renderZone();
      else if (state.step === 3) content = renderBindings();
      else if (state.step === 4) content = renderSettings();
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
                    ? activateRevision
                : state.errorOperation === "delete"
                  ? deleteDraft
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
      deleteDraft,
      saveDraft,
      validateDraft,
      canonicalizeDraft,
      activateRevision,
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
    isWizardCandidateCompatible,
    rankCandidates,
    createSetupWizard,
  };
})(typeof window !== "undefined" ? window : globalThis);
