/*
 * Controlel application shell — mock data only.
 *
 * This is the mock "backend state" for the prototype. Presentation components
 * (components.js / app.js) only render what is defined here; they never infer
 * configuration truth on their own.
 *
 * Truthfulness rules (see AGENTS.md) are respected in the mock values:
 *   - temperatures are sensor *reports*, not physical confirmation;
 *   - the heat source state is a *permission* state, not burner state;
 *   - unknown stays unknown (no invented states).
 *
 * Nothing here is a live Home Assistant value. No backend calls are made.
 */
(function (global) {
  "use strict";

  global.MOCK_APP_DATA = {
    app: {
      name: "Controlel",
      provider: "home_assistant",
      providerInstanceId: "ha-core-7f3c91",
      version: "prototype 0.1",
      lastUpdated: "2026-08-21 10:15",
    },

    // Module states: active | incomplete | attention | disabled | not_configured
    modules: [
      {
        id: "heating",
        label: "Heating",
        state: "incomplete",
        summary: "1 zone configured · setup draft saved with 2 blocking items",
        warningCount: 2,
        updatedAt: "2026-08-21 09:41",
        primaryAction: { label: "Continue setup", route: "setup" },
        secondaryAction: { label: "Open Heating", route: "heating" },
        order: 1,
        hidden: false,
      },
      {
        id: "smart-charging",
        label: "Smart Charging",
        state: "not_configured",
        stateLabel: "Not configured · coming later",
        summary: "EV charging optimization is not part of this prototype yet.",
        warningCount: 0,
        order: 2,
        hidden: false,
      },
      {
        id: "lighting",
        label: "Lighting",
        state: "not_configured",
        stateLabel: "Not configured · coming later",
        summary: "Lighting scenarios are not part of this prototype yet.",
        warningCount: 0,
        order: 3,
        hidden: false,
      },
      {
        id: "water-safety",
        label: "Water Safety",
        state: "not_configured",
        stateLabel: "Not configured · coming later",
        summary: "Leak detection and shutoff coordination are not part of this prototype yet.",
        warningCount: 0,
        order: 4,
        hidden: false,
      },
    ],

    // Important warnings/issues surfaced on the Overview.
    issues: [
      {
        severity: "warning",
        code: "SETUP_INCOMPLETE",
        message: "Heating setup is incomplete — 2 blocking items remain before it can become active.",
      },
      {
        severity: "warning",
        code: "SENSOR_CONFIRMATION_REQUIRED",
        message: "The primary temperature sensor is an important binding and still needs explicit confirmation.",
      },
    ],

    heating: {
      zone: {
        name: "Living Room",
        area: "area.living_room",
      },
      currentTemperature: {
        value: "21.4",
        unit: "°C",
        sub: "Reported by sensor.living_room_temperature · not physical confirmation",
      },
      targetTemperature: {
        value: "21.0",
        unit: "°C",
        sub: "Comfort target for the zone",
      },
      demand: {
        state: "idle",
        label: "No heating demand",
        sub: "Assessment: reported temperature is at/above target",
      },
      heatSource: {
        state: "unknown",
        label: "Heat source permission: not granted",
        sub: "Permission state only — a successful command is not physical confirmation",
      },
      status: {
        state: "incomplete",
        reason: "SETUP_INCOMPLETE",
        message:
          "Setup draft is saved but incomplete. The heating module cannot become active until the blocking items are resolved.",
      },
      completeness: {
        configured: 3,
        total: 5,
        items: [
          { label: "Zone", state: "configured" },
          { label: "Primary temperature sensor", state: "configured" },
          { label: "Heat source (enable/disable)", state: "configured" },
          { label: "Sensor confirmation", state: "incomplete" },
          { label: "Heat source confirmation", state: "incomplete" },
        ],
      },
      recentEventIds: ["evt-003", "evt-002", "evt-001"],
    },

    // Activity / diagnostics events.
    // level: basic | detailed | debug — the diagnostics view filters by the
    // selected maximum level (Basic shows basic only, Debug shows everything).
    activity: [
      {
        id: "evt-001",
        at: "2026-08-21 09:30",
        level: "basic",
        category: "setup",
        title: "Discovery snapshot captured",
        message: "A read-only Home Assistant discovery snapshot was captured for the setup wizard.",
        reasonCodes: ["SNAPSHOT_CAPTURED"],
        metadata: {
          snapshotId: "snap-20260821-0930",
          fingerprint: "sha256:9c1f4e2a…b7d3",
          counts: { floors: 2, areas: 5, devices: 14, entities: 42 },
        },
      },
      {
        id: "evt-002",
        at: "2026-08-21 09:38",
        level: "basic",
        category: "setup",
        title: "Zone selected",
        message: "Living Room was selected as the heating zone (recommendation accepted).",
        reasonCodes: ["ZONE_SELECTED", "RECOMMENDATION_ACCEPTED"],
        metadata: { zone: "zone.living-room", area: "area.living_room", origin: "RECOMMENDATION_ACCEPTED" },
      },
      {
        id: "evt-003",
        at: "2026-08-21 09:41",
        level: "basic",
        category: "setup",
        title: "Setup draft saved (incomplete)",
        message: "The heating setup draft was saved with 2 blocking items. It can be finished later.",
        reasonCodes: ["DRAFT_SAVED", "SETUP_INCOMPLETE", "SENSOR_CONFIRMATION_REQUIRED"],
        metadata: {
          revisionId: "rev-a1b2c3",
          blocking: ["SENSOR_CONFIRMATION_REQUIRED", "HEAT_SOURCE_CONFIRMATION_REQUIRED"],
          savedAt: "2026-08-21T09:41:00+02:00",
        },
      },
      {
        id: "evt-004",
        at: "2026-08-21 09:41:02",
        level: "detailed",
        category: "validation",
        title: "Validation report computed",
        message: "Deterministic validation of the exact draft revision produced 2 blocking items and 0 warnings.",
        reasonCodes: ["VALIDATION_COMPUTED", "SENSOR_CONFIRMATION_REQUIRED", "HEAT_SOURCE_CONFIRMATION_REQUIRED"],
        metadata: {
          revisionId: "rev-a1b2c3",
          blocking: 2,
          warnings: 0,
          activationReady: false,
        },
      },
      {
        id: "evt-005",
        at: "2026-08-21 09:41:02",
        level: "detailed",
        category: "zone",
        title: "Zone demand assessed: no heating demand",
        message: "Reported zone temperature is at/above the comfort target; no heat delivery was requested.",
        reasonCodes: ["ZONE_AT_TARGET", "DEMAND_ASSESSED"],
        metadata: {
          zone: "zone.living-room",
          reportedTemperature: "21.4°C",
          targetTemperature: "21.0°C",
          sensor: "sensor.living_room_temperature",
        },
      },
      {
        id: "evt-006",
        at: "2026-08-21 09:41:03",
        level: "debug",
        category: "system",
        title: "Adapter state sync (mock)",
        message: "The (mock) Home Assistant adapter reported a consistent registry state. No drift detected.",
        reasonCodes: ["ADAPTER_SYNC", "NO_DRIFT"],
        metadata: {
          adapterVersion: "0.1.0",
          providerInstanceId: "ha-core-7f3c91",
          registryFingerprint: "sha256:9c1f4e2a…b7d3",
          drift: { renamed: 0, disappeared: 0, replaced: 0 },
        },
      },
      {
        id: "evt-007",
        at: "2026-08-21 09:41:03",
        level: "debug",
        category: "system",
        title: "Event retention check (mock)",
        message: "Activity history is within the bounded retention window; nothing was dropped.",
        reasonCodes: ["RETENTION_OK"],
        metadata: { retained: 7, dropped: 0, window: "24h" },
      },
    ],

    // Settings overview — navigation/structure only, not a settings form.
    settings: [
      {
        id: "heating-config",
        label: "Heating configuration",
        description: "Zone, sensor and heat source bindings for the heating module.",
        state: "incomplete",
        action: { label: "Continue setup", route: "setup" },
        order: 1,
        hidden: false,
      },
      {
        id: "notifications",
        label: "Notifications",
        description: "Choose which Controlel events are surfaced (placeholder).",
        state: "not_configured",
        order: 2,
        hidden: false,
      },
      {
        id: "diagnostics",
        label: "Diagnostics level",
        description: "Basic, Detailed or Debug display level for the activity view.",
        state: "ok",
        action: { label: "Open Diagnostics", route: "diagnostics" },
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
    ],
  };
})(typeof window !== "undefined" ? window : globalThis);
