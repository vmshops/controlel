/*
 * Controlel Water Safety wizard — basic behavior tests (Node).
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { Element, documentStub } = require("./dom-stub");

global.document = documentStub;

require("../i18n.js");
require("../api-client.js");
require("../components.js");
require("../water-wizard.js");

const CA_WATER_WIZARD = globalThis.CA_WATER_WIZARD;

test("createSetupWaterWizard exposes seven manual steps", () => {
  assert.equal(CA_WATER_WIZARD.STEPS.length, 7);
  assert.equal(CA_WATER_WIZARD.STEPS[0].key, "wizard.water.step_discovery");
  assert.equal(CA_WATER_WIZARD.STEPS[4].key, "wizard.water.step_sirens");
});

test("createSetupWaterWizard renders discovery idle state", () => {
  const root = new Element("div");
  const panel = new Element("section"); panel.id = "water-step-panel";
  const stepper = new Element("nav"); stepper.id = "water-stepper";
  const footer = new Element("footer"); footer.id = "water-wizard-footer";
  const draftStatus = new Element("div"); draftStatus.id = "water-draft-status";
  root.append(panel, stepper, footer, draftStatus);
  documentStub._root = root;

  const client = {
    discover: () => Promise.reject(new Error("not used")),
    recommendations: () => Promise.reject(new Error("not used")),
    startDraft: () => Promise.reject(new Error("not used")),
    reopenDraft: () => Promise.reject(new Error("not used")),
    updateDraft: () => Promise.reject(new Error("not used")),
    validateDraft: () => Promise.reject(new Error("not used")),
  };

  const wizard = CA_WATER_WIZARD.createSetupWaterWizard({
    client,
    configEntryId: "entry-1",
    root,
    storage: null,
  });

  assert.ok(wizard);
  assert.equal(wizard.state.step, 1);
  assert.ok(panel.textContent.includes("Discover Home Assistant objects"));
});

test("rolesWithPrefix filters recommendation roles", () => {
  const recommendations = [
    { role: "water_safety.moisture_sensor" },
    { role: "water_safety.notification.primary" },
    { role: "water_safety.siren.hall" },
    { role: "heating.primary_temperature" },
  ];
  assert.deepEqual(
    CA_WATER_WIZARD.rolesWithPrefix(recommendations, "water_safety.notification."),
    ["water_safety.notification.primary"]
  );
});
