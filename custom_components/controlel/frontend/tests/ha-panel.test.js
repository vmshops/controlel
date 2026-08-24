/* Controlel Home Assistant custom-panel lifecycle regression tests. */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { Element, documentStub } = require("./dom-stub");

class HTMLElementStub extends Element {}

const registry = new Map();
const bootstrapCalls = [];

documentStub.head = new Element("head");
documentStub._root = new Element("div");
documentStub.head.appendChild = function appendAndLoad(node) {
  this.append(node);
  queueMicrotask(() => {
    if (typeof node.onload === "function") node.onload();
  });
  return node;
};

global.document = documentStub;
global.HTMLElement = HTMLElementStub;
global.customElements = {
  define(name, constructor) { registry.set(name, constructor); },
  get(name) { return registry.get(name); },
};
global.window = {
  document: documentStub,
  CA: {
    bootstrap(options) {
      bootstrapCalls.push(options);
      return { options };
    },
  },
};

require("../ha-panel.js");

const Panel = registry.get("controlel-panel");

function loadShadowStyles(panel) {
  const appendChild = panel.shadowRoot.appendChild.bind(panel.shadowRoot);
  panel.shadowRoot.appendChild = (node) => {
    const result = appendChild(node);
    queueMicrotask(() => {
      if (typeof node.onload === "function") node.onload();
    });
    return result;
  };
}

async function flushLifecycle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test("custom panel forwards HA lifecycle properties and scopes CSS to its shadow root", async () => {
  const panel = new Panel();
  loadShadowStyles(panel);
  const connection = { sendMessagePromise() {} };
  const panelInfo = { config: { config_entry_id: "entry-real-ha" } };
  const route = { prefix: "/controlel", path: "/controlel" };

  panel.hass = { connection };
  panel.panel = panelInfo;
  panel.narrow = true;
  panel.route = route;
  panel.connectedCallback();
  await flushLifecycle();

  assert.equal(bootstrapCalls.length, 1);
  assert.equal(bootstrapCalls[0].root, panel.shadowRoot);
  assert.equal(bootstrapCalls[0].hass.connection, connection);
  assert.equal(bootstrapCalls[0].panel, panelInfo);
  assert.equal(bootstrapCalls[0].config.config_entry_id, "entry-real-ha");
  assert.equal(bootstrapCalls[0].narrow, true);
  assert.equal(bootstrapCalls[0].route, route);
  assert.equal(panel.hasAttribute("narrow"), true);

  const shadowLinks = panel.shadowRoot.children.filter((node) => node.tagName === "LINK");
  const documentLinks = documentStub.head.children.filter((node) => node.tagName === "LINK");
  assert.equal(shadowLinks.length, 1, "one stylesheet is attached to the panel shadow root");
  assert.equal(shadowLinks[0].href, "/controlel_static/styles.css");
  assert.equal(documentLinks.length, 0, "panel CSS is not leaked into document.head");
});

test("custom panel reboots only for connection/config changes and remains reconnect-safe", async () => {
  const panel = new Panel();
  loadShadowStyles(panel);
  const firstConnection = { sendMessagePromise() {} };
  panel.hass = { connection: firstConnection };
  panel.panel = { config: { config_entry_id: "entry-1" } };
  panel.connectedCallback();
  await flushLifecycle();
  const initialCalls = bootstrapCalls.length;

  panel.hass = { connection: firstConnection, states: { updated: true } };
  assert.equal(bootstrapCalls.length, initialCalls, "ordinary hass updates do not rebuild the shell");

  const secondConnection = { sendMessagePromise() {} };
  panel.hass = { connection: secondConnection };
  assert.equal(bootstrapCalls.length, initialCalls + 1, "a replacement connection is handed off");

  panel.panel = { config: { config_entry_id: "entry-2" } };
  assert.equal(bootstrapCalls.length, initialCalls + 2, "a replacement config entry is handed off");

  panel.disconnectedCallback();
  panel.connectedCallback();
  await flushLifecycle();
  assert.equal(bootstrapCalls.length, initialCalls + 3, "reconnect performs exactly one fresh bootstrap");
  assert.equal(
    panel.shadowRoot.children.filter((node) => node.tagName === "LINK").length,
    1,
    "reconnect does not duplicate the scoped stylesheet"
  );
});
