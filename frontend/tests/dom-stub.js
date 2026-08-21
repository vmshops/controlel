/*
 * Minimal DOM stub for running the Controlel frontend behavior tests in Node.
 *
 * It implements only what components.js / app.js / wizard.js actually use:
 *   - document.createElement / createTextNode / getElementById
 *   - element: className, id, hidden/checked/disabled, setAttribute,
 *     append, replaceChildren, addEventListener, dispatch
 *   - text nodes with nodeType 3
 *
 * It is intentionally not a general-purpose DOM. Tests also use the
 * findAll / findByText helpers exported here.
 */
"use strict";

class TextNode {
  constructor(text) {
    this.nodeType = 3;
    this.textContent = String(text);
    this.parentNode = null;
  }
}

class Element {
  constructor(tagName) {
    this.nodeType = 1;
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.parentNode = null;
    this.style = {};
    this._hidden = false;
    this._checked = false;
    this._disabled = false;
  }

  get className() { return this.attributes.class || ""; }
  set className(value) { this.attributes.class = String(value); }

  get id() { return this.attributes.id || ""; }
  set id(value) { this.attributes.id = String(value); }

  get hidden() { return this._hidden; }
  set hidden(value) { this._hidden = Boolean(value); }

  get checked() { return this._checked; }
  set checked(value) { this._checked = Boolean(value); }

  get disabled() { return this._disabled; }
  set disabled(value) { this._disabled = Boolean(value); }

  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return Object.prototype.hasOwnProperty.call(this.attributes, key) ? this.attributes[key] : null; }
  hasAttribute(key) { return Object.prototype.hasOwnProperty.call(this.attributes, key); }

  append(...nodes) {
    for (const node of nodes) {
      if (node === null || node === undefined) continue;
      if (node.parentNode) node.parentNode.children = node.parentNode.children.filter((c) => c !== node);
      node.parentNode = this;
      this.children.push(node);
    }
  }

  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }

  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }

  /** Test helper: invoke listeners registered for `type`. */
  dispatch(type, event) {
    for (const fn of this.listeners[type] || []) fn(event || { type, target: this });
  }

  /** Test helper: depth-first walk over descendant elements. */
  *walk() {
    for (const child of this.children) {
      if (child.nodeType === 1) {
        yield child;
        yield* child.walk();
      }
    }
  }

  get textContent() {
    return this.children.map((c) => (c.nodeType === 3 ? c.textContent : c.textContent)).join("");
  }

  set textContent(value) {
    this.children = [];
    if (value !== "" && value !== null && value !== undefined) this.append(new TextNode(value));
  }

  /**
   * Test helper: find all descendant elements whose class list contains
   * every class in `classes` (space-separated string).
   */
  findAll(classes) {
    const wanted = String(classes).split(/\s+/).filter(Boolean);
    const out = [];
    for (const el of this.walk()) {
      const have = el.className.split(/\s+/).filter(Boolean);
      if (wanted.every((w) => have.includes(w))) out.push(el);
    }
    return out;
  }

  /** Test helper: find the first descendant element containing `text`. */
  findByText(text) {
    for (const el of this.walk()) {
      if (el.textContent.includes(text)) return el;
    }
    return null;
  }

  /** Test helper: find a descendant button by its exact text. */
  findButton(text) {
    for (const el of this.walk()) {
      if (el.tagName === "BUTTON" && el.textContent.trim() === text) return el;
    }
    return null;
  }
}

const documentStub = {
  createElement: (tag) => new Element(tag),
  createTextNode: (text) => new TextNode(text),
  _root: null,
  getElementById(id) {
    if (!this._root) return null;
    for (const el of this._root.walk()) {
      if (el.id === id) return el;
    }
    return null;
  },
};

module.exports = { Element, TextNode, documentStub };
