# Controlel — External Tester Guide

This guide is for a technically capable Home Assistant user who wants to test
Controlel 0.12.0. You do not need to know how Controlel works internally.
Everything you need is explained here, in plain language.

Controlel is a heating control integration. It watches one room temperature
sensor, compares it with your target temperature, and decides when to ask a
heat source switch to turn on or off — with built-in safety rules that prevent
the boiler from cycling too quickly.

---

## 1. Before testing

- **Home Assistant version:** `2026.7.3` or newer.
- **HACS** must be installed (it is the normal way to install Controlel).
- **Back up your Home Assistant configuration** before installing. This is an
  early testing version; a backup makes any problem easy to undo.
- **You need two existing Home Assistant entities:**
  - a **temperature sensor** (a `sensor` entity with a temperature device
    class, reporting °C or °F), and
  - a **switch** that can safely turn your heat source on and off (for
    example a boiler enable switch). Use a dedicated entity with appropriate
    hardware interlocks — Controlel cannot verify that the target is physically
    safe.
- **This is an early testing version.** Expect rough edges. Nothing Controlel
  does should be treated as a final behavior, and it is not a substitute for
  your own heating safety devices.

---

## 2. Installation

1. Open HACS and select **Custom repositories** from the top-right menu.
2. Add `https://github.com/vmshops/controlel` with category **Integration**.
3. Open Controlel in HACS and download the latest released version.
4. **Restart Home Assistant** when HACS asks you to.
5. Open **Settings > Devices & services > Add integration**, search for
   **Controlel**, and complete the setup form.

That is all. Home Assistant installs the required core package automatically —
do not install anything else manually.

---

## 3. First setup walkthrough

The setup form asks for four things:

- **Zone name** — a friendly name for the room or area you are heating
  (for example "Living room"). Controlel currently supports one zone.
- **Temperature sensor** — pick the sensor that measures the room temperature.
  The list is filtered to temperature sensors only.
- **Target temperature** — the temperature you want in the room. The default
  is 21.0 °C. You can change it later in **Configure**.
- **Heat source switch** — the switch Controlel may turn on and off to control
  heating. In simple mode you only pick the switch; Controlel uses its
  standard on/off calls.

After setup, a device named **Controlel — \<your zone name\>** appears in
Home Assistant. Its entities show the current and target temperature, whether
Controlel currently wants heat, the safety state, and diagnostic details.

A full description of every entity is in the
[entity reference](../operations/EntityReference.md).

---

## 4. What to test

Work through this checklist in order. Note anything that does not match.

- [ ] **Integration loads** — after restart, Controlel appears in
      **Settings > Devices & services** with no errors.
- [ ] **Device appears** — the `Controlel — <zone name>` device exists.
- [ ] **Entities are available** — current temperature, target temperature,
      heat demand, and safety state entities show sensible values.
- [ ] **Temperature changes create expected demand** — lower the target
      temperature (or let the room cool) and confirm Controlel reports that it
      wants heat; raise the target (or warm the room) and confirm the demand
      goes away. Remember the hysteresis and confirmation delays described in
      section 5 — small or brief changes may not react immediately.
- [ ] **Heat source command behavior** — when Controlel decides it needs heat,
      the configured switch receives an on command; when it no longer needs
      heat, it receives an off command. Watch the "requested command" and
      "service call outcome" entities.
- [ ] **Safety behavior** — once a command is sent, Controlel should not
      immediately send the opposite command (minimum on/off times). If you
      change the target back and forth quickly, the switch should not flap.
- [ ] **Diagnostics** — download the config entry diagnostics
      (device menu > **Download diagnostics**) and check that it contains
      readable configuration, versions, and an operational snapshot.

---

## 5. Things that may surprise testers

These are intentional design decisions, not bugs:

- **A command is not a physical confirmation.** "Service call dispatched"
  means Home Assistant accepted the call to your switch. It does *not* mean
  the boiler is actually firing or the valve is open. Controlel never claims
  to know the physical state of your heating equipment.
- **Heating permission is not the same as the burner running.** Controlel
  decides that heat is *wanted* and *allowed*; whether the burner physically
  runs is outside its knowledge.
- **Delays are intentional.**
  - *Hysteresis* (default 0.3 °C below / 0.1 °C above the target) prevents
    the switch from flipping on tiny temperature wiggles.
  - *Heat-demand confirmation* (default 2 minutes) filters brief sensor dips
    before a demand is accepted.
  - *Anti-cycling* (default 10 minutes minimum on, 5 minutes minimum off)
    protects the boiler from rapid on/off cycling.
- **No persistence after restart.** Controlel keeps its state in memory only.
  After a Home Assistant restart it re-reads the current sensor value and
  starts fresh — it does not reconstruct what happened before the restart.
- **Notifications are disabled by default.** Controlel will not send you
  Home Assistant notifications unless you explicitly configure recipients.

---

## 6. Reporting problems

When something looks wrong, please include:

1. **Controlel version** (shown in the integration's diagnostic entities and
   in the diagnostics download).
2. **Home Assistant version** (Settings > System > Overview).
3. **Installation method** (HACS custom repository, or manual).
4. **Screenshots** of the relevant entities or the setup form.
5. **Diagnostics download** — device menu > **Download diagnostics**. This is
   the single most useful artifact; it contains the normalized configuration,
   versions, and the current operational snapshot.
6. **Relevant logs** — Home Assistant logs around the time of the problem,
   especially anything mentioning `controlel`.

More background on what diagnostics contain:
[diagnostics reference](../operations/Diagnostics.md). General help:
[installation guide](../operations/HomeAssistantInstallation.md) and
[troubleshooting](../operations/Troubleshooting.md).

---

## 7. Tester feedback questions

Your honest impressions matter as much as bug reports. Please answer:

- Was the installation process understandable?
- Where did you hesitate or get stuck during setup?
- Which entity names or values were confusing?
- Did you understand *why* heating did or did not activate at a given moment?
- Did the safety delays (hysteresis, confirmation, minimum on/off) feel
  reasonable, or did they surprise you?
- What would you change about the setup form or the default values?

Thank you for testing!
