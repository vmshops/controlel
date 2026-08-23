/*
 * Controlel setup wizard — mock data only.
 *
 * Shapes intentionally mirror the setup architecture concepts
 * (docs/architecture/09_Setup_Discovery_and_Import.md):
 *   - a read-only discovery snapshot (structure + advertised capability),
 *   - deterministic role recommendations with confidence + reason codes,
 *   - candidates that carry identity quality and evidence,
 *   - important bindings that require explicit confirmation.
 *
 * Nothing here is a live Home Assistant value.
 */
(function (global) {
  "use strict";

  global.MOCK_SETUP_DATA = {
    snapshot: {
      provider: "home_assistant",
      providerInstanceId: "ha-core-7f3c91",
      snapshotId: "snap-20260821-0930",
      capturedAt: "2026-08-21T09:30:00+02:00",
      adapterVersion: "0.1.0",
      fingerprint: "sha256:9c1f4e2a…b7d3",
      counts: { floors: 2, areas: 5, devices: 14, entities: 42 },
    },

    roles: {
      zone: {
        label: "Room / zone",
        important: false,
        recommendedId: "zone.living-room",
        candidates: [
          {
            id: "zone.living-room",
            name: "Living Room",
            locator: "area.living_room",
            area: "Living Room",
            identityQuality: "STABLE",
            confidence: "HIGH",
            reasons: ["AREA_MATCH", "HEAT_DELIVERY_DEVICE_PRESENT"],
            evidence: "Area registry entry on floor 'Ground'; 2 radiator devices assigned.",
          },
          {
            id: "zone.bedroom",
            name: "Bedroom",
            locator: "area.bedroom",
            area: "Bedroom",
            identityQuality: "STABLE",
            confidence: "MEDIUM",
            reasons: ["AREA_MATCH", "HEAT_DELIVERY_DEVICE_PRESENT"],
            evidence: "Area registry entry on floor 'First'; 1 radiator device assigned.",
          },
          {
            id: "zone.office",
            name: "Office",
            locator: "area.office",
            area: "Office",
            identityQuality: "STABLE",
            confidence: "LOW",
            reasons: ["AREA_MATCH", "NO_HEAT_DELIVERY_DEVICE"],
            evidence: "Area registry entry on floor 'First'; no heat delivery device assigned.",
          },
        ],
      },

      sensor: {
        label: "Primary temperature sensor",
        important: true,
        recommendedId: "sensor.living-room",
        candidates: [
          {
            id: "sensor.living-room",
            name: "Living Room Temperature",
            locator: "sensor.living_room_temperature",
            area: "Living Room",
            identityQuality: "STABLE",
            confidence: "HIGH",
            reasons: ["TEMPERATURE_DEVICE_CLASS", "UNIT_CELSIUS", "SHARED_AREA"],
            evidence: "device_class=temperature, unit=°C, area=Living Room.",
          },
          {
            id: "sensor.living-room-combined",
            name: "Living Room Combined Sensor",
            locator: "sensor.living_room_combined",
            area: "Living Room",
            identityQuality: "STABLE",
            confidence: "MEDIUM",
            reasons: ["TEMPERATURE_DEVICE_CLASS", "SHARED_AREA"],
            evidence: "Multi-measurement device; temperature channel selected.",
          },
          {
            id: "sensor.hallway",
            name: "Hallway Temperature",
            locator: "sensor.hallway_temperature",
            area: "Hallway",
            identityQuality: "STABLE",
            confidence: "LOW",
            reasons: ["TEMPERATURE_DEVICE_CLASS", "UNIT_CELSIUS", "AREA_MISMATCH"],
            evidence: "device_class=temperature, unit=°C, area=Hallway.",
          },
        ],
      },

      heatSource: {
        label: "Heat source (enable/disable)",
        important: true,
        recommendedId: "source.boiler",
        candidates: [
          {
            id: "source.boiler",
            name: "Boiler Enable",
            locator: "input_boolean.boiler_enable",
            identityQuality: "STABLE",
            confidence: "HIGH",
            reasons: ["ENABLE_DISABLE_SERVICE", "AREA_MATCH"],
            evidence: "Advertised enable/disable service; area=Boiler room.",
          },
          {
            id: "source.boiler-pump",
            name: "Boiler Pump",
            locator: "switch.boiler_pump",
            identityQuality: "STABLE",
            confidence: "MEDIUM",
            reasons: ["ENABLE_DISABLE_SERVICE"],
            evidence: "Switch with turn_on/turn_off services.",
          },
          {
            id: "source.script",
            name: "Boiler Script",
            locator: "script.boiler_on",
            identityQuality: "EPHEMERAL",
            confidence: "LOW",
            reasons: ["SERVICE_ONLY", "NO_REGISTRY_IDENTITY"],
            evidence: "Script without stable registry identity; rename recovery not guaranteed.",
          },
        ],
      },
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
