/*
 * Controlel — Frontend API v1 client / adapter layer.
 *
 * This is the ONLY place that talks to the backend. It uses the Home
 * Assistant frontend's existing authenticated WebSocket connection
 * (the custom panel's `hass.connection`) and never creates its own transport or
 * authentication. Components consume the normalized models produced here,
 * not HA internals.
 *
 * Responsibilities:
 *   - send the four read-only Frontend API v1 commands
 *     (controlel/frontend_api/v1/{overview,heating,diagnostics,setup});
 *   - send the non-activating Setup Write API v1 discovery, recommendation,
 *     draft, reopen, update, and validation commands;
 *   - normalize + validate each response into a stable model shape
 *     (unknown/null backend values stay null — nothing is invented);
 *   - expose a data source with explicit per-domain states:
 *     loading / loaded / error (disconnected, timeout, request error);
 *   - provide an EXPLICIT demo mode that maps the existing mock data into
 *     the same model shape. Demo mode is never a silent fallback for a
 *     failed real request.
 *
 * The module is Node-safe (no DOM) so the behavior tests in tests/ can
 * exercise it without a browser.
 */
(function (global) {
  "use strict";

  const COMMANDS = {
    overview: "controlel/frontend_api/v1/overview",
    heating: "controlel/frontend_api/v1/heating",
    diagnostics: "controlel/frontend_api/v1/diagnostics",
    setup: "controlel/frontend_api/v1/setup",
  };

  const SETUP_WRITE_COMMANDS = {
    discovery: "controlel/setup/write/v1/discovery",
    recommendations: "controlel/setup/write/v1/recommendations",
    start: "controlel/setup/write/v1/start",
    reopen: "controlel/setup/write/v1/reopen",
    update: "controlel/setup/write/v1/update",
    validate: "controlel/setup/write/v1/validate",
  };

  const DOMAINS = Object.keys(COMMANDS);

  /**
   * Documented mapping from the backend event severity to the shell's
   * display levels (Basic / Detailed / Debug). This is a presentation
   * choice only; it does not alter the underlying severity.
   */
  const SEVERITY_LEVEL = {
    info: "basic",
    notice: "basic",
    warning: "detailed",
    critical: "debug",
  };

  /** Typed, non-throwing-across-boundary error for adapter failures. */
  class ApiError extends Error {
    constructor(kind, message, domain) {
      super(message);
      this.name = "ApiError";
      this.kind = kind; // disconnected | timeout | error | invalid_response
      this.domain = domain || null;
    }
  }

  // ------------------------------------------------------------ validation

  function _obj(value, name) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      throw new ApiError("invalid_response", `${name} must be an object`);
    }
    return value;
  }

  function _arr(value, name) {
    if (!Array.isArray(value)) {
      throw new ApiError("invalid_response", `${name} must be an array`);
    }
    return value;
  }

  function _strOrNull(value) {
    return typeof value === "string" ? value : null;
  }

  function _numOrNull(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function _scope(value) {
    if (value && typeof value === "object" && !Array.isArray(value)) return value;
    return { type: "unknown" };
  }

  function _checkVersion(raw, name) {
    const r = _obj(raw, name);
    if (r.frontend_api_version !== 1) {
      throw new ApiError("invalid_response", `unsupported frontend_api_version in ${name}`);
    }
    return r;
  }

  // ---------------------------------------------------------- normalizers
  //
  // Each normalizer validates the required shape and returns a stable model.
  // Optional values are coerced to null so the UI can render "unknown"
  // instead of guessing.

  function normalizeOverview(raw) {
    const r = _checkVersion(raw, "overview");
    const system = _obj(r.system, "overview.system");
    return {
      frontend_api_version: 1,
      generated_at: _strOrNull(r.generated_at),
      system: {
        status: system.status,
        operating_mode: _strOrNull(system.operating_mode),
        operating_mode_reason: _strOrNull(system.operating_mode_reason),
        operating_mode_since: _strOrNull(system.operating_mode_since),
      },
      modules: _arr(r.modules, "overview.modules").map((m) => {
        const o = _obj(m, "overview.module");
        return { module_id: o.module_id, status: o.status, reason: _strOrNull(o.reason) };
      }),
      attention: _arr(r.attention, "overview.attention").map((a) => {
        const o = _obj(a, "overview.attention item");
        return {
          attention_id: o.attention_id,
          severity: o.severity,
          code: o.code,
          scope: _scope(o.scope),
          summary: _strOrNull(o.summary),
          first_seen_at: _strOrNull(o.first_seen_at),
        };
      }),
    };
  }

  function _decisionSummary(value) {
    if (!value || typeof value !== "object") return null;
    return {
      decision_id: value.decision_id,
      action: value.action,
      observed_at: _strOrNull(value.observed_at),
      reason_code: _strOrNull(value.reason_code),
    };
  }

  function normalizeHeating(raw) {
    const r = _checkVersion(raw, "heating");
    const building = _obj(r.building, "heating.building");
    const hs = _obj(building.heat_source, "heating.building.heat_source");
    return {
      frontend_api_version: 1,
      generated_at: _strOrNull(r.generated_at),
      building: {
        demand_status: building.demand_status,
        demand_reason_code: _strOrNull(building.demand_reason_code),
        heat_source: {
          permission: hs.permission,
          requested_command: hs.requested_command === undefined ? null : hs.requested_command,
          command_outcome: hs.command_outcome === undefined ? null : hs.command_outcome,
          reported_state: hs.reported_state,
          physical_state: hs.physical_state === undefined ? "unknown" : hs.physical_state,
          last_decision_summary: _decisionSummary(hs.last_decision_summary),
        },
      },
      zones: _arr(r.zones, "heating.zones").map((z) => {
        const o = _obj(z, "heating.zone");
        return {
          zone_id: o.zone_id,
          name: o.name,
          current_temperature_c: _numOrNull(o.current_temperature_c),
          measurement_state: o.measurement_state,
          measurement_age_seconds: _numOrNull(o.measurement_age_seconds),
          target_temperature_c: _numOrNull(o.target_temperature_c),
          demand_state: o.demand_state,
          demand_reason_code: _strOrNull(o.demand_reason_code),
          last_decision: _decisionSummary(o.last_decision),
        };
      }),
    };
  }

  function normalizeDiagnostics(raw) {
    const r = _checkVersion(raw, "diagnostics");
    const health = _obj(r.health, "diagnostics.health");
    const stream = _obj(health.event_stream, "diagnostics.health.event_stream");
    const trace = r.decision_trace;
    return {
      frontend_api_version: 1,
      generated_at: _strOrNull(r.generated_at),
      health: {
        runtime_status: health.runtime_status,
        operating_mode: health.operating_mode,
        event_stream: {
          total_emitted: _numOrNull(stream.total_emitted) || 0,
          retained: _numOrNull(stream.retained) || 0,
          dropped: _numOrNull(stream.dropped) || 0,
        },
      },
      recent_events: _arr(r.recent_events, "diagnostics.recent_events").map((e) => {
        const o = _obj(e, "diagnostics.event");
        const command = o.command && typeof o.command === "object"
          ? { action: o.command.action === undefined ? null : o.command.action, outcome: o.command.outcome === undefined ? null : o.command.outcome }
          : null;
        return {
          event_id: o.event_id,
          timestamp: _strOrNull(o.timestamp),
          category: o.category,
          severity: o.severity,
          event_code: o.event_code,
          summary_code: _strOrNull(o.summary_code),
          reason_code: _strOrNull(o.reason_code),
          scope: _scope(o.scope),
          previous_state: _strOrNull(o.previous_state),
          new_state: _strOrNull(o.new_state),
          command,
          level: SEVERITY_LEVEL[o.severity] || "basic",
        };
      }),
      decision_trace: trace && typeof trace === "object"
        ? {
            decision_id: trace.decision_id,
            zone_id: trace.zone_id,
            sensor_id: trace.sensor_id,
            action: trace.action,
            observed_at: _strOrNull(trace.observed_at),
            reason_code: _strOrNull(trace.reason_code),
            evidence: Array.isArray(trace.evidence) ? trace.evidence : [],
            retained_count: _numOrNull(trace.retained_count) || 0,
            total_decisions: _numOrNull(trace.total_decisions) || 0,
          }
        : null,
    };
  }

  function normalizeSetup(raw) {
    const r = _checkVersion(raw, "setup");
    const readiness = _obj(r.readiness, "setup.readiness");
    return {
      frontend_api_version: 1,
      generated_at: _strOrNull(r.generated_at),
      readiness: { state: readiness.state, reason_code: _strOrNull(readiness.reason_code) },
      missing_configuration: _arr(r.missing_configuration, "setup.missing_configuration").map((m) => {
        const o = _obj(m, "setup.missing_configuration item");
        return { code: o.code, scope: _scope(o.scope), severity: o.severity };
      }),
      validation_messages: _arr(r.validation_messages, "setup.validation_messages").map((v) => {
        const o = _obj(v, "setup.validation_messages item");
        return { code: o.code, severity: o.severity, scope: _scope(o.scope), summary: _strOrNull(o.summary) };
      }),
    };
  }

  const NORMALIZERS = {
    overview: normalizeOverview,
    heating: normalizeHeating,
    diagnostics: normalizeDiagnostics,
    setup: normalizeSetup,
  };

  // ------------------------------------------------------------- client

  /**
   * Create a read-only client bound to one HA connection + config entry.
   *
   * @param {object} opts
   * @param {object} opts.connection      HA connection (must expose sendMessagePromise)
   * @param {string} opts.configEntryId   Controlel config entry id
   * @param {number} [opts.timeoutMs]     per-request timeout (default 15000)
   */
  function createFrontendApiClient({ connection, configEntryId, timeoutMs = 15000 }) {
    if (!connection || typeof connection.sendMessagePromise !== "function") {
      throw new ApiError("disconnected", "No Home Assistant connection is available");
    }
    if (typeof configEntryId !== "string" || configEntryId.length === 0) {
      throw new ApiError("disconnected", "A Controlel config_entry_id is required");
    }

    function call(domain) {
      return new Promise((resolve, reject) => {
        let settled = false;
        const timer = setTimeout(() => {
          fail(new ApiError("timeout", "The request timed out before a response arrived", domain));
        }, timeoutMs);

        function fail(err) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          reject(err);
        }

        function succeed(value) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(value);
        }

        try {
          connection.sendMessagePromise({
            type: COMMANDS[domain],
            config_entry_id: configEntryId,
          }).then(
            (result) => {
              if (settled) return;
              try {
                // HA resolves sendMessagePromise with the successful
                // `result` payload directly, not the WebSocket envelope.
                succeed(NORMALIZERS[domain](result));
              } catch (err) {
                fail(err instanceof ApiError ? err : new ApiError("invalid_response", "Unexpected response shape", domain));
              }
            },
            (err) => {
              const message =
                (err && err.error && err.error.message) ||
                (err && err.message) ||
                "The request failed";
              fail(new ApiError("error", message, domain));
            }
          );
        } catch (err) {
          fail(new ApiError("disconnected", (err && err.message) || String(err), domain));
        }
      });
    }

    return {
      overview: () => call("overview"),
      heating: () => call("heating"),
      diagnostics: () => call("diagnostics"),
      setup: () => call("setup"),
    };
  }

  // ------------------------------------------------------ setup write client

  function normalizeDiscoverySnapshot(raw) {
    const r = _obj(raw, "setup discovery");
    const counts = _obj(r.object_counts, "setup discovery.object_counts");
    return {
      snapshot_id: r.snapshot_id,
      provider: r.provider,
      provider_instance_id: r.provider_instance_id,
      captured_at: _strOrNull(r.captured_at),
      content_fingerprint: r.content_fingerprint,
      object_counts: { ...counts },
      objects: _arr(r.objects, "setup discovery.objects").map((item) => ({
        ..._obj(item, "setup discovery object"),
      })),
    };
  }

  function normalizeCandidate(raw) {
    const r = _obj(raw, "setup candidate");
    return {
      candidate_id: r.candidate_id,
      role: r.role,
      native_id: _strOrNull(r.native_id),
      current_locator: _strOrNull(r.current_locator),
      identity_quality: r.identity_quality,
      area_id: _strOrNull(r.area_id),
      floor_id: _strOrNull(r.floor_id),
      capabilities: _arr(r.capabilities, "setup candidate.capabilities").slice(),
      confidence: r.confidence,
      reason_codes: _arr(r.reason_codes, "setup candidate.reason_codes").slice(),
      evidence: { ..._obj(r.evidence, "setup candidate.evidence") },
    };
  }

  function normalizeRecommendations(raw) {
    return _arr(raw, "setup recommendations").map((item) => {
      const r = _obj(item, "setup recommendation");
      return {
        role: r.role,
        recommended: r.recommended === null ? null : normalizeCandidate(r.recommended),
        alternatives: _arr(r.alternatives, "setup recommendation.alternatives").map(normalizeCandidate),
        explicit_confirmation_required: Boolean(r.explicit_confirmation_required),
      };
    });
  }

  function normalizeSetupSession(raw) {
    const r = _obj(raw, "setup session");
    return {
      ...r,
      draft_id: r.draft_id,
      draft_revision: r.draft_revision,
      settings: { ..._obj(r.settings, "setup session.settings") },
      selections: _arr(r.selections, "setup session.selections").map((item) => ({
        ..._obj(item, "setup session selection"),
      })),
      recommendations: normalizeRecommendations(r.recommendations),
      validation_issues: _arr(r.validation_issues, "setup session.validation_issues").map((item) => ({
        ..._obj(item, "setup validation issue"),
      })),
      discovery: normalizeDiscoverySnapshot(r.discovery),
      canonical_revision_id: _strOrNull(r.canonical_revision_id),
      active_revision_id: _strOrNull(r.active_revision_id),
    };
  }

  const SETUP_RESULT_NORMALIZERS = {
    discovery: normalizeDiscoverySnapshot,
    recommendations: normalizeRecommendations,
    start: normalizeSetupSession,
    reopen: normalizeSetupSession,
    update: normalizeSetupSession,
    validate: normalizeSetupSession,
  };

  /**
   * Create the authenticated, setup-only write client. It exposes draft and
   * validation operations only: there is deliberately no canonicalize,
   * activate, runtime, or Home Assistant service-call method.
   */
  function createSetupWriteClient({ connection, configEntryId, timeoutMs = 15000 }) {
    if (!connection || typeof connection.sendMessagePromise !== "function") {
      throw new ApiError("disconnected", "No Home Assistant connection is available");
    }
    if (typeof configEntryId !== "string" || configEntryId.length === 0) {
      throw new ApiError("disconnected", "A Controlel config_entry_id is required");
    }

    function call(operation, payload) {
      return new Promise((resolve, reject) => {
        let settled = false;
        const timer = setTimeout(() => {
          fail(new ApiError("timeout", "The setup request timed out before a response arrived", "setup"));
        }, timeoutMs);

        function fail(error) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          reject(error);
        }

        function succeed(value) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(value);
        }

        const message = {
          ...(payload && typeof payload === "object" ? payload : {}),
          type: SETUP_WRITE_COMMANDS[operation],
          config_entry_id: configEntryId,
        };
        try {
          connection.sendMessagePromise(message).then(
            (raw) => {
              try {
                const envelope = _obj(raw, `setup ${operation} response`);
                if (envelope.setup_write_api_version !== 1 || envelope.operation !== operation) {
                  throw new ApiError("invalid_response", `Unsupported setup ${operation} response`, "setup");
                }
                succeed(SETUP_RESULT_NORMALIZERS[operation](envelope.result));
              } catch (error) {
                fail(error instanceof ApiError ? error : new ApiError("invalid_response", "Unexpected setup response shape", "setup"));
              }
            },
            (error) => {
              const messageText =
                (error && error.error && error.error.message) ||
                (error && error.message) ||
                "The setup request failed";
              const apiError = new ApiError("error", messageText, "setup");
              apiError.code = (error && error.code) || (error && error.error && error.error.code) || null;
              fail(apiError);
            }
          );
        } catch (error) {
          fail(new ApiError("disconnected", (error && error.message) || String(error), "setup"));
        }
      });
    }

    return {
      discover: (request) => call("discovery", request),
      recommendations: (request) => call("recommendations", request),
      startDraft: (request) => call("start", request),
      reopenDraft: (request) => call("reopen", request),
      updateDraft: (request) => call("update", request),
      validateDraft: (request) => call("validate", request),
    };
  }

  // ------------------------------------------------- environment detect

  /**
   * Detect the HA frontend environment. Returns the authenticated
   * connection and the config entry id when both are available.
   *
   * The config entry id is read from the panel config (when the panel is
   * registered by the integration) or from an explicit `?entry=` URL
   * parameter. Neither is authentication — the WS connection is HA's.
   */
  function detectHaEnvironment(win, context) {
    const w = win || (typeof window !== "undefined" ? window : null);
    const supplied = context && typeof context === "object" ? context : null;
    const hasSuppliedHass = supplied && Object.prototype.hasOwnProperty.call(supplied, "hass");
    const hass = hasSuppliedHass ? supplied.hass : w && w.hass;
    const connection = hass && hass.connection;
    const hasConnection = Boolean(connection && typeof connection.sendMessagePromise === "function");

    let configEntryId = null;
    const panelConfig = supplied
      ? supplied.panelConfig || (supplied.panel && supplied.panel.config) || null
      : w && w.panelConfig;
    if (panelConfig && typeof panelConfig.config_entry_id === "string" && panelConfig.config_entry_id) {
      configEntryId = panelConfig.config_entry_id;
    } else if (w && w.location && typeof w.location.search === "string" && w.location.search) {
      try {
        const entry = new URLSearchParams(w.location.search).get("entry");
        if (entry) configEntryId = entry;
      } catch (_err) {
        /* ignore malformed query strings */
      }
    }

    return {
      available: hasConnection && Boolean(configEntryId),
      connection: hasConnection ? connection : null,
      configEntryId,
      reason: !hasConnection ? "no_ha_connection" : !configEntryId ? "missing_config_entry_id" : null,
    };
  }

  // -------------------------------------------------------- data sources

  /**
   * Real data source: each domain method resolves to
   * {status:"loaded", data} or {status:"error", error}. It NEVER falls back
   * to mock data on failure.
   */
  function createRealDataSource(client) {
    const make = (domain) => () =>
      client[domain]().then(
        (data) => ({ status: "loaded", data }),
        (error) => ({ status: "error", error })
      );
    return {
      mode: "real",
      overview: make("overview"),
      heating: make("heating"),
      diagnostics: make("diagnostics"),
      setup: make("setup"),
    };
  }

  // ------------------------------------------------------------- demo mode

  /**
   * Map the existing mock app data into the same normalized model shapes the
   * real adapter produces. This is an EXPLICIT demo/development mode only;
   * the mapping is documented and lossy by design (the mock vocabulary is
   * richer/different than the API vocabulary).
   */
  function mockToModels(mock) {
    const heating = (mock && mock.heating) || {};
    const status = heating.status ? heating.status.state : "unknown";

    const systemStatus = status === "active" ? "active" : status === "disabled" ? "stopped" : "degraded";
    const generatedAt = mock && mock.app && mock.app.lastUpdated ? mock.app.lastUpdated : null;

    const overview = {
      frontend_api_version: 1,
      generated_at: generatedAt,
      system: {
        status: systemStatus,
        operating_mode: "demo",
        operating_mode_reason: "Demo mode — mock data, not a live Home Assistant value",
        operating_mode_since: null,
      },
      modules: ((mock && mock.modules) || []).map((m) => ({
        module_id: m.id,
        status: m.state === "active" ? "active" : m.state === "attention" ? "error" : "inactive",
        reason:
          m.state === "incomplete" ? "Setup incomplete (demo)"
          : m.state === "attention" ? "Needs attention (demo)"
          : m.state === "not_configured" ? "Not configured (demo)"
          : null,
      })),
      attention: ((mock && mock.issues) || []).map((i, idx) => ({
        attention_id: `demo-attention-${idx}`,
        severity: i.severity === "warning" ? "warning" : "info",
        code: i.code,
        scope: { type: "system" },
        summary: i.message,
        first_seen_at: null,
      })),
    };

    const zone = heating.zone || {};
    const cur = heating.currentTemperature;
    const tgt = heating.targetTemperature;
    const demandIdle = heating.demand && heating.demand.state === "idle";
    const curValue = cur && cur.value !== null && cur.value !== undefined && cur.value !== "" ? Number(cur.value) : null;
    const tgtValue = tgt && tgt.value !== null && tgt.value !== undefined && tgt.value !== "" ? Number(tgt.value) : null;

    const heatingModel = {
      frontend_api_version: 1,
      generated_at: generatedAt,
      building: {
        demand_status: demandIdle ? "no_heat_required" : "indeterminate",
        demand_reason_code: demandIdle ? "ZONE_AT_TARGET" : null,
        heat_source: {
          permission: "disabled",
          requested_command: null,
          command_outcome: null,
          reported_state: "DISABLED",
          physical_state: "unknown",
          last_decision_summary: null,
        },
      },
      zones: [{
        zone_id: "zone.demo",
        name: zone.name || "Zone",
        current_temperature_c: curValue,
        measurement_state: curValue === null ? "missing" : "fresh",
        measurement_age_seconds: null,
        target_temperature_c: tgtValue,
        demand_state: demandIdle ? "no_heat_required" : "indeterminate",
        demand_reason_code: demandIdle ? "ZONE_AT_TARGET" : null,
        last_decision: null,
      }],
    };

    const activity = (mock && mock.activity) || [];
    const diagnostics = {
      frontend_api_version: 1,
      generated_at: generatedAt,
      health: {
        runtime_status: systemStatus,
        operating_mode: "demo",
        event_stream: { total_emitted: activity.length, retained: activity.length, dropped: 0 },
      },
      recent_events: activity.map((e) => ({
        event_id: e.id,
        timestamp: e.at,
        category: e.category,
        severity: e.level === "debug" ? "warning" : e.level === "detailed" ? "notice" : "info",
        event_code: (e.reasonCodes && e.reasonCodes[0]) || e.category,
        summary_code: e.title,
        reason_code: (e.reasonCodes && e.reasonCodes[0]) || null,
        scope: { type: "system" },
        previous_state: null,
        new_state: null,
        command: null,
        level: e.level || "basic",
      })),
      decision_trace: null,
    };

    const issues = (mock && mock.issues) || [];
    const setup = {
      frontend_api_version: 1,
      generated_at: generatedAt,
      readiness: {
        state: status === "incomplete" ? "incomplete" : status === "active" ? "ready" : "unknown",
        reason_code: heating.status && heating.status.reason ? heating.status.reason : null,
      },
      missing_configuration: issues.map((i) => ({ code: i.code, scope: { type: "system" }, severity: "error" })),
      validation_messages: issues.map((i) => ({
        code: i.code,
        severity: i.severity === "warning" ? "warning" : "error",
        scope: { type: "system" },
        summary: i.message,
      })),
    };

    return { overview, heating: heatingModel, diagnostics, setup };
  }

  /**
   * Demo data source: resolves immediately from mock data. Only used when
   * demo mode is explicitly enabled — never as a fallback for real failures.
   */
  function createDemoDataSource(mockAppData) {
    const models = mockToModels(mockAppData);
    const make = (domain) => () => Promise.resolve({ status: "loaded", data: models[domain] });
    return {
      mode: "demo",
      overview: make("overview"),
      heating: make("heating"),
      diagnostics: make("diagnostics"),
      setup: make("setup"),
    };
  }

  global.CA_API = {
    COMMANDS,
    SETUP_WRITE_COMMANDS,
    DOMAINS,
    SEVERITY_LEVEL,
    ApiError,
    normalizeOverview,
    normalizeHeating,
    normalizeDiagnostics,
    normalizeSetup,
    normalizeDiscoverySnapshot,
    normalizeRecommendations,
    normalizeSetupSession,
    createFrontendApiClient,
    createSetupWriteClient,
    detectHaEnvironment,
    createRealDataSource,
    mockToModels,
    createDemoDataSource,
  };
})(typeof window !== "undefined" ? window : globalThis);
