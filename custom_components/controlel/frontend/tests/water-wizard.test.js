/*
 * Controlel Water Safety wizard ÔÇö lifecycle behavior tests (Node).
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

function makeClient() {
  const calls = [];
  const client = {
    calls,
    discover: () => Promise.reject(new Error("not used")),
    recommendations: () => Promise.reject(new Error("not used")),
    startDraft: () => Promise.reject(new Error("not used")),
    reopenDraft: () => Promise.reject(new Error("not used")),
    updateDraft: (payload) => {
      calls.push(["updateDraft", payload]);
      return Promise.resolve({
        draft_id: "draft-1",
        draft_revision: 2,
        settings: {},
        selections: [],
        recommendations: [],
        validation_issues: [],
        validation_status: "NOT_VALIDATED",
        activation_ready: false,
        blocking_issue_count: 0,
        warning_count: 0,
        discovery: { snapshot_id: "snapshot-1", object_counts: {} },
        canonical_revision_id: null,
        active_revision_id: null,
      });
    },
    validateDraft: (payload) => {
      calls.push(["validateDraft", payload]);
      return Promise.resolve({
        draft_id: "draft-1",
        draft_revision: 2,
        settings: {},
        selections: [],
        recommendations: [],
        validation_issues: [],
        validation_status: "CURRENT",
        activation_ready: true,
        blocking_issue_count: 0,
        warning_count: 0,
        discovery: { snapshot_id: "snapshot-1", object_counts: {} },
        canonical_revision_id: null,
        active_revision_id: null,
      });
    },
    canonicalizeDraft: (payload) => {
      calls.push(["canonicalizeDraft", payload]);
      return Promise.resolve({
        draft_id: "draft-1",
        draft_revision: 2,
        settings: {},
        selections: [],
        recommendations: [],
        validation_issues: [],
        validation_status: "CURRENT",
        activation_ready: true,
        blocking_issue_count: 0,
        warning_count: 0,
        discovery: { snapshot_id: "snapshot-1", object_counts: {} },
        canonical_revision_id: "canonical-rev-1",
        active_revision_id: null,
      });
    },
    activateDraft: (payload) => {
      calls.push(["activateDraft", payload]);
      return Promise.resolve({
        draft_id: "draft-1",
        draft_revision: 2,
        settings: {},
        selections: [],
        recommendations: [],
        validation_issues: [],
        validation_status: "CURRENT",
        activation_ready: true,
        blocking_issue_count: 0,
        warning_count: 0,
        discovery: { snapshot_id: "snapshot-1", object_counts: {} },
        canonical_revision_id: "canonical-rev-1",
        active_revision_id: "canonical-rev-1",
      });
    },
  };
  return client;
}

function mountWizard(client) {
  const root = new Element("div");
  const panel = new Element("section"); panel.id = "water-step-panel";
  const stepper = new Element("nav"); stepper.id = "water-stepper";
  const footer = new Element("footer"); footer.id = "water-wizard-footer";
  const draftStatus = new Element("div"); draftStatus.id = "water-draft-status";
  root.append(panel, stepper, footer, draftStatus);
  documentStub._root = root;

  const wizard = CA_WATER_WIZARD.createSetupWaterWizard({
    client,
    configEntryId: "entry-1",
    root,
    storage: null,
    now: () => "2026-08-29T08:00:00Z",
    idFactory: (prefix) => `${prefix}-fixed`,
  });
  wizard.state.session = {
    draft_id: "draft-1",
    draft_revision: 1,
    settings: {},
    selections: [],
    recommendations: [],
    validation_issues: [],
    validation_status: "NOT_VALIDATED",
    activation_ready: false,
    blocking_issue_count: 0,
    warning_count: 0,
    canonical_revision_id: null,
    active_revision_id: null,
  };
  wizard.state.snapshot = { snapshot_id: "snapshot-1", object_counts: {}, objects: [] };
  wizard.state.status = "loaded";
  wizard.state.step = 7;
  wizard.render();
  return { wizard, panel, client };
}

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

test("water wizard runs explicit save validate canonicalize activate lifecycle", async () => {
  const client = makeClient();
  const { wizard } = mountWizard(client);
  const session = {
    draft_id: "draft-1",
    draft_revision: 1,
    validation_report_id: "report-1",
    settings: { area_id: "area-1", sensor_id: "sensor-1" },
    selections: [],
    recommendations: [],
    validation_issues: [],
    validation_status: "CURRENT",
    activation_ready: true,
    blocking_issue_count: 0,
    warning_count: 0,
    canonical_revision_id: null,
    active_revision_id: null,
    discovery: { snapshot_id: "snapshot-1", object_counts: {}, objects: [] },
  };
  Object.assign(wizard.state, {
    step: 7,
    status: "loaded",
    dirty: false,
    snapshot: session.discovery,
    session,
  });
  wizard.render();

  const saved = await wizard.saveDraft();
  assert.ok(saved);
  await wizard.validateDraft();
  await wizard.canonicalizeDraft();
  await wizard.activateDraft();

  assert.deepEqual(client.calls.map(([operation]) => operation), [
    "updateDraft",
    "validateDraft",
    "canonicalizeDraft",
    "activateDraft",
  ]);
  assert.equal(wizard.state.session.active_revision_id, "canonical-rev-1");
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
