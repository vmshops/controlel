# Shadow Runtime and Behavioral Simulation

Status: Architecture proposal

## Purpose

The Controlel Shadow Runtime is an operational behavior simulation and
validation laboratory. It runs ordinary Controlel control logic against
virtual inputs, devices, time, and lifecycle events so that behavior can be
examined without affecting a real installation.

It answers questions such as:

- What decisions does Controlel make when a sensor becomes unavailable?
- Are source protection and safety deadlines preserved through unusual event
  ordering?
- What happens when a device command fails or reported state conflicts with a
  requested command?
- Does restart, reload, or user intervention preserve the documented
  contracts?
- Does a candidate configuration produce different decisions from the active
  configuration for the same evidence?

The laboratory validates software behavior. It is not a model of a house.

## Goals

- Run unchanged Controlel domain and application logic in deterministic virtual
  environments.
- Substitute real providers and effectful ports only at composition boundaries.
- Support passive comparison, authored scenarios, controlled random
  exploration, and replay.
- Represent sensor failure, device unavailability, user actions, restarts,
  conflicts, and other operational conditions as explicit timeline events.
- Make scenarios human-readable, versioned, importable, exportable,
  deterministic, and reproducible.
- Capture inputs, runtime results, commands, operational events, diagnostics,
  failures, and assertions in an explainable report.
- Keep `REAL` and `SHADOW_SIMULATION` evidence unmistakably separate on every
  exported surface.
- Provide a module-neutral simulation kernel. Heating is the first module
  adapter, not a special case in the kernel.

## Non-goals

Shadow does not provide:

- building, room, or thermal physics;
- heat-loss, weather, solar-gain, hydraulic, CFD, or energy models;
- automatic temperature response after a heating command;
- a realistic digital twin;
- inferred physical device state from successful commands;
- adaptive production configuration or automatic remediation;
- a second control engine or a simulation branch inside production control;
- a polling loop that attempts to imitate elapsed time;
- direct access to real command adapters from a simulation run.

A simulated source-enable dispatch means only that the virtual port accepted
the request. It does not mean that a burner ran. A simulated actuator command
does not change reported position unless a separate scenario event supplies
that report.

## Placement in the existing architecture

The current core already has the necessary seams:

- `Clock` provides aware application time.
- `Scheduler` installs one-shot callbacks.
- `HeatSourcePort` and `HeatDeliveryActuatorPort` isolate command effects.
- public runtime methods accept normalized measurement, reported-state,
  operating-mode, and lifecycle inputs.
- immutable runtime results, operational events, performance observations, and
  diagnostics expose behavior without becoming control inputs.

The proposed package belongs outside the domain and application layers:

```text
Production                                      Simulation

Home Assistant providers/adapters               Scenario/timeline providers
              |                                               |
Home Assistant composition root                 Simulation module adapter
              |                                               |
              +------ shared runtime assembly contract -------+
                                      |
                         unchanged core runtime
                                      |
                     domain + application policies
```

The intended dependency direction is:

```text
                         controlel.domain
                                ^
                                |
                      controlel.application
                         ^              ^
                         |              |
custom_components/controlel       controlel.simulation
```

`controlel.simulation` is an outer laboratory/composition package. It may
import public domain and application contracts. Domain and application code
must never import simulation code. Production infrastructure and normal Home
Assistant composition do not import simulation code, and simulation does not
import `custom_components`. A future Passive Shadow integration may use a
separate outermost composition adapter that depends on both sides without
making either side depend on the other.

Production and simulation must not independently duplicate runtime wiring.
They call a shared, production-neutral runtime assembly contract that accepts
only configuration and public domain/application ports. That assembly code
depends only on domain and application contracts: it cannot import Home
Assistant, simulation providers, or concrete effectful adapters. Each outer
composition root remains responsible for supplying its own providers and
ports. This keeps runtime policies, defaults, and service construction equal
without introducing environment flags into core.

The existing `ShadowHeatingPerformanceMonitor` is not this runtime. It is a
bounded M31C passive performance observer attached to one real runtime. It
remains unchanged and can be one source of evidence in a simulation report.
Likewise, `FakeTemperatureSensorProvider` remains a small test helper; it is
not a timeline engine, virtual clock, or failure-capable simulation provider.

## Non-negotiable boundary rules

1. Core control code contains no `if shadow`, simulation mode, scenario ID, or
   random generator.
2. Production and Shadow compose the same runtime type and policies through
   the shared runtime assembly contract.
3. Simulation inputs enter through the same public normalized boundaries used
   by a real adapter. Scenarios never mutate private stores or policy state.
4. Simulation outputs terminate in runner-owned recording ports and isolated
   Shadow trace sinks. They cannot reach Home Assistant services, MQTT,
   physical devices, production operational-event/history stores, or
   notification transports.
5. Command request, dispatch outcome, reported device state, assessment, and
   physical reality remain separate facts.
6. Unknown remains unknown. Replay never fills gaps using inferred state.
7. Safety, minimum on/off protection, deferred commands, failure handling, and
   runtime supervision are the real production implementations.
8. Virtual time advances only because the timeline has a next event or a core
   scheduler has a next deadline. There is no periodic simulation tick.

## Architecture components

### Simulation environment

A simulation environment owns one isolated run:

- immutable run identity and origin metadata;
- selected scenario and module composition;
- virtual clock;
- deterministic one-shot scheduler;
- module-specific virtual providers and recording ports;
- the ordinary runtime instance;
- ordered input/output trace;
- assertion evaluator and final report.

No mutable runtime, scheduler, port, or trace object is shared between a real
environment and a Shadow environment, or between two Shadow runs.

The runner accepts only nominal `TrustedSimulationAdapter` implementations
owned and reviewed with the simulation outer layer. Structural callables and
arbitrary protocol-compatible factories are rejected. This is a fixed
reviewed in-package code boundary, not plugin registration, runtime security
allowlisting, or a sandbox. Trusted adapters construct only simulation-owned
recording ports and isolated sinks; they do not accept production command or
notification adapters from callers.

### Module-neutral simulation kernel

The kernel owns mechanics that are common to every Controlel module:

- scenario parsing and validation;
- virtual time and deterministic queue ordering;
- lifecycle orchestration;
- mandatory environment provenance;
- trace capture;
- expectation evaluation orchestration;
- replay metadata;
- report construction;
- seeded exploration coordination.

It does not know what a temperature, charger, light, leak sensor, alarm, media
player, boiler, or valve means.

### Explicit module adapter

Each supported Controlel module supplies an explicitly injected simulation
adapter. Version 1 does not need dynamic plugin discovery or a generic plugin
framework.

A module adapter is responsible for:

- validating its `initial_state` and event payloads;
- invoking the shared runtime assembly contract with runner-owned virtual
  implementations of production ports/providers;
- translating scenario events into public normalized runtime calls;
- capturing module runtime results and observable snapshots;
- exposing module-specific assertions and comparison fields;
- stopping and reconstructing the runtime for lifecycle events.

The first adapter will be heating. Later adapters can implement the same narrow
boundary for Smart Charging, Lighting, Water Safety, Security, and Media
Control. Multiple-module scenarios are deferred until single-module execution
and replay are stable.

### Virtual providers

Virtual providers own scenario-supplied external evidence. Examples include
sensor values and availability, reported device state, occupancy or window
state, tariff/weather inputs, and user actions when a production module has a
corresponding provider boundary.

A provider does not calculate missing evidence. A frozen sensor repeats the
same explicitly configured reading and timestamp behavior. An unavailable
sensor supplies the module adapter's ordinary unavailable/indeterminate input.
If production core has no concept or provider for an event such as DHW state or
window state, the module adapter rejects that scenario event as unsupported;
Shadow must not add a simulation-only control input.

### Recording command ports

Virtual command ports implement the same application port contracts as real
adapters. For every request they record:

- virtual time;
- exact typed command;
- configured dispatch outcome;
- normalized failure type when applicable;
- environment and run identity.

Port behavior is controlled by explicit scenario state such as `available`,
`unavailable`, `succeed`, or `fail`. A successful dispatch updates only command
outcome evidence. Reported device state changes only through an independent
provider event.

### Runtime lifecycle adapter

Start, stop, reload, runtime failure, and restart are environment operations,
not special branches in core. The lifecycle adapter creates or disposes an
ordinary runtime composition and invokes its existing public lifecycle and
handover boundaries.

REAL and SHADOW use the same production-neutral startup sequence: record the
runtime start, begin source recovery, ingest any initial reported-source
evidence, then ingest initial temperature or indeterminate evidence. Recovery
therefore governs every evaluation caused by initial evidence, and neither
environment can dispatch from a fresh runtime before the same recovery and
reconciliation policies have run.

A restart begins with only the state explicitly supported by the selected
restart contract. Volatile state is reset. Persisted or handover evidence must
be present in the scenario or captured trace; transition history and physical
state are never reconstructed.

## Shadow modes

### Passive Shadow

Passive Shadow observes normalized real inputs and runs an isolated candidate
runtime beside production:

```text
real provider input
       |
       +--> production runtime --> real ports
       |
       +--> immutable mirror --> Shadow runtime --> recording ports
```

The mirror copies accepted adapter-level evidence, its timestamp, ordering,
and stable subject identity. Production remains authoritative. Shadow output
cannot feed production ports, runtime state, configuration, or notifications.

Passive comparison is based on correlated input sequence/checkpoints, not on
timestamp proximity. A comparison can report:

- same observable decision;
- different decision or reason;
- extra or missing command request;
- different deadline or safety state;
- different diagnostic/anomaly transition;
- comparison unavailable because evidence or initial state was incomplete.

Counterfactual device outcomes must be declared. Shadow cannot assume that a
real successful dispatch implies reported or physical success. A newly started
Passive Shadow may require a warm-up period because private historical state
cannot be reconstructed from current physical observations.

### Scenario Simulation

Scenario Simulation executes a versioned authored document against one module
adapter. All external changes are explicit timeline events. No input changes
because a command was emitted unless the scenario separately says so.

Representative events include:

- sensor value, unavailable, stale, conflicting, or frozen behavior;
- reported device state or device availability change;
- virtual command-port failure/recovery;
- user action or manual operating-mode request;
- external condition change exposed by a production provider;
- runtime start, stop, reload, crash, or restart;
- diagnostics/report checkpoint.

### Automated Exploration

Automated Exploration generates bounded meaningful scenarios and executes them
through the same Scenario Simulation runner.

Every exploration configuration defines:

- deterministic PRNG algorithm and seed;
- generator version;
- supported event vocabulary and capabilities;
- duration, event-count, value, and failure bounds;
- valid ordering/combination constraints;
- invariants and expectations to check.

A failure always saves the fully materialized canonical scenario, not only the
seed. The seed and generator metadata explain how it was found; the exported
scenario is the replay authority even if a later generator changes. Automated
shrinking/minimization is useful future work, not required for the first
foundation.

Exploration does not use AI, mutate private runtime state, generate unbounded
random input, or decide that unusual automatically means unsafe.

### Replay

Replay is not a separate execution engine. It imports a canonical scenario and
runs it through Scenario Simulation using the same ordering rules.

Sources of replay scenarios include:

- an authored scenario;
- an Automated Exploration finding;
- an exported Passive Shadow input trace;
- a redacted real-operation capture.

Real captures contain only observed facts. Missing startup history, unknown
reported state, and dropped evidence remain explicit. Replay may therefore be
`inconclusive`; it must not fabricate a complete initial state.

## Origin and environment provenance

The mandatory origin vocabulary is:

- `REAL`
- `SHADOW_SIMULATION`

Origin is assigned by the trusted production adapter or simulation runner. It
is not accepted as an arbitrary scenario event value and is never used by core
decision logic.

Every exported input event, runtime result, command record, reported-state
record, operational event, state snapshot, diagnostic, comparison, assertion,
and error is wrapped or projected with:

```text
origin
environment_id
run_id
mode
scenario_id (when applicable)
```

Shadow adds this metadata at capture/presentation boundaries rather than
changing existing core event and state models. A raw core object must never be
shown in a mixed Reality/Shadow UI, log, history, or export without its
environment envelope. Passive Shadow retains separate record IDs and an
explicit `source_real_record_id` when a simulated input was mirrored from real
evidence.

Provenance does not make a shared production sink safe. REAL and
SHADOW_SIMULATION records use separate streams, repositories, history
namespaces, and retention policies by default. Shadow operational events and
diagnostics cannot enter production `OperationalEventStream`, UserActivity,
notification processing, or real diagnostic history. Comparison reads
immutable REAL captures and isolated Shadow traces; it never merges their
writable paths. Presentation code must visibly label origin and exclude Shadow
records from REAL views unless the user explicitly selects a comparison view.

Example report context:

```yaml
environment:
  origin: SHADOW_SIMULATION
  environment_id: shadow-local
  run_id: run-000042
  mode: scenario
  scenario_id: room_sensor_failure_during_heating
```

## Scenario model

### Top-level contract

A scenario document contains:

- `schema_version`;
- stable `scenario_id`, human name, and optional description/tags;
- module and module-adapter contract version;
- aware virtual `start_at`;
- explicit module configuration or an authoring-time configuration fixture
  reference;
- explicit `initial_state`;
- ordered `timeline` events;
- machine-readable `expectations`;
- optional exploration provenance.

YAML is the primary human-readable authoring representation and is supplied by
the optional `simulation` package extra; importing the production runtime core
does not require a YAML parser. Import first
resolves fixtures and deterministic defaults into a complete normalized
scenario. Canonical JSON bytes, not YAML text, are the replay and content-hash
authority. Canonicalization normalizes timestamps, durations, numbers, key
ordering, and generated event sequence IDs so behaviorally identical inputs
hash identically.

A fixture name is authoring convenience, not sufficient replay evidence.
Canonical export embeds the resolved effective configuration and records the
fixture identity and content hash when a fixture was used. Replay never
silently re-resolves a mutable fixture by name. Secrets are removed before
export; if removing a value would affect behavior, export must fail or use an
explicit non-secret replay substitute rather than claim reproducibility.

Example:

```yaml
schema_version: 1
scenario_id: room_sensor_failure_during_heating
name: Room sensor failure during heating
module: heating
module_contract_version: 1
start_at: 2026-01-15T08:00:00Z

configuration:
  fixture: one_zone_safe_defaults

initial_state:
  zone_temperature: 19.5
  target_temperature: 21.0
  source_reported_state: unknown

timeline:
  - at: 0m
    event:
      type: runtime.start

  - at: 10m
    event:
      type: sensor.availability_changed
      subject: living_room_temperature
      payload:
        availability: unavailable

expectations:
  - type: operational_event.exists
    event_code: measurement_became_unavailable

  - type: invariant.holds
    invariant: source_protection_preserved
```

The example does not predict room temperature and does not claim a source is
physically running.

### Initial state

Initial state describes only facts that a real provider, persisted contract,
or public handover boundary could supply. Omitted values default to unknown or
module-defined fresh construction, never to a favorable physical state.

Scenarios cannot initialize private stores directly. The module adapter must
establish state using configuration, public startup inputs, and supported
handover contracts. Unsupported initial-state fields are validation errors.

### Timeline event envelope

Every timeline item has:

- relative `at` duration or aware absolute time defining when the input is
  delivered to the runtime;
- stable sequence derived from file order;
- optional same-time phase;
- namespaced event type;
- stable subject identity when applicable;
- validated scalar/structured payload.

Delivery time and evidence time are distinct. An evidence-producing payload
may carry the aware timestamp at which the external observation occurred; this
can be earlier than, equal to, or later than delivery time so stale, delayed,
future-dated, and out-of-order evidence can be represented truthfully. A
module contract may define omitted evidence time as equal to delivery time,
but the canonical scenario materializes that default. Lifecycle and user
events that are not observations have no fabricated evidence timestamp.

Event types describe supplied evidence or lifecycle operations, not desired
internal decisions. For example, `device.reported_state_changed` is valid;
`controller.set_internal_source_state` is not.

### Expectations

Expectations assert observable behavior. Initial assertion families should be
small:

- event exists/does not exist;
- command sequence or command absence;
- runtime result/status/reason;
- diagnostic field/value;
- deadline scheduled/cancelled;
- invariant holds;
- no unhandled error;
- Passive Shadow trace equality/difference at a checkpoint.

Human labels such as `safe_behavior` must resolve to a documented
module-specific invariant. They cannot be an unimplemented free-text oracle.
An unsupported expectation fails scenario validation rather than silently
passing.

## Deterministic timeline engine

The timeline engine uses virtual aware time and never sleeps. Its queue contains
scenario events and callbacks installed through the ordinary `Scheduler` port.

Execution is serialized. The next item advances the virtual clock exactly to
its delivery timestamp, executes one operation to completion, captures outputs,
and then continues. Each execution record distinguishes `scheduled_for`,
`delivered_at`, and any payload observation/evidence timestamp. A callback may
schedule another callback using the same scheduler. Cancellation is best effort
at the port contract but deterministic within a declared virtual-scheduler
policy; stale callback protection remains the responsibility of the unchanged
core.

Virtual time never moves backwards. A runtime callback scheduled at or before
the current instant executes at the current instant, retaining its original
`scheduled_for` value and recording the current `delivered_at`. Invalid
scenario delivery times before `start_at` are rejected. Deterministic late
delivery and already-queued-after-cancellation fault policies are compatible
future extensions; v0.1 uses exact delivery unless work is scheduled in the
past during the current operation.

Same-time ordering is explicit:

1. scenario events in the `before_deadlines` phase, in document order;
2. core scheduled callbacks, in scheduler insertion order;
3. scenario events in the `after_deadlines` phase, in document order.

The default scenario phase is `before_deadlines`. Tests concerned with an exact
deadline boundary must state the phase so the case is readable. The report
records the resolved global sequence.

The engine executes newly scheduled work at the current timestamp until the
queue is empty. A configured transition limit fails the run with a deterministic
`timeline_livelock` error instead of hanging.

## Replay and reproducibility contract

A reproducible export records:

- canonical normalized JSON scenario and its content hash;
- scenario, module-contract, trace, and report schema versions;
- Controlel core and simulation package versions;
- module adapter and assertion-contract versions;
- virtual start time plus canonicalization, semantic-fingerprint, scheduler,
  and timeline-ordering policy versions;
- normalized effective configuration with secrets removed, including fixture
  identity/content hash when applicable;
- exploration algorithm, generator version, and seed when applicable;
- all materialized external input events;
- explicit initial-state completeness and dropped-evidence indicators.

Replaying the same canonical scenario with the same declared implementation
and policy versions must produce the same semantic observable trace and
assertion outcomes. A semantic trace fingerprint is calculated from normalized
inputs and observable outputs. It excludes ephemeral values such as generated
`run_id`, export time, storage IDs, and wall-clock capture metadata. Reports may
differ in those run-specific fields while retaining the same semantic
fingerprint.

Running a scenario against another core, adapter, policy, or configuration
version is allowed for comparison, but it is a new run and must report both
version sets. Compatibility failures are explicit; the importer never guesses
at breaking schema changes or silently substitutes current defaults.

## Trace capture and reporting

The simulation report is an immutable, exportable read model. It contains:

- environment and origin metadata;
- scenario identity/hash and implementation versions;
- seed/generator provenance;
- start/end virtual timestamps and ordered execution counts;
- normalized executed inputs;
- runtime results and scheduled-deadline records;
- requested commands and dispatch outcomes;
- separately reported device evidence;
- operational events and selected diagnostics;
- assertion results with evidence record IDs;
- semantic trace fingerprint and the fields excluded from that fingerprint;
- Passive Shadow differences when applicable;
- normalized errors and an overall `passed`, `failed`, `error`, or
  `inconclusive` outcome.

Reports retain command/observation/assessment/decision separation. They do not
send notifications directly. Any future user notification must be derived
through the existing UserActivity and notification policy pipeline.

Report retention may be bounded for interactive runs, but truncation and drop
counts must be explicit. A saved failure artifact must retain the canonical
scenario needed for replay even when verbose trace evidence is truncated.

## Versioning policy

Scenario, trace, and report schemas are versioned independently.

- Additive optional fields or fields with deterministic defaults are backward
  compatible and keep the current schema version.
- Breaking semantic changes, type changes, renamed/removed required fields, or
  incompatible ordering changes increment the affected schema version.
- Module event payloads are validated against the declared module contract
  version.
- Scheduler ordering and assertion semantics have explicit policy/contract
  versions in replay metadata; a behavior-changing policy revision cannot be
  presented as an identical replay.
- Canonicalization and semantic-fingerprint algorithms are versioned replay
  policies. Algorithm changes may retain document schema compatibility but
  cannot reuse an old hash/fingerprint without identifying the old policy.
- Importers reject unsupported major schema/contract versions with a stable
  error; they do not coerce unknown events or drop expectations.
- Explicit, deterministic migrations may create a new canonical document while
  retaining the source document hash and version. A migrated document receives
  its own canonical hash, and reports identify both source and migrated forms.

## Safety and isolation

A shipped Shadow composition must not contain an effectful production command
or notification transport. Reviewed in-package adapters create only
simulation-owned recording ports and isolated Shadow sinks; their trust is a
composition/code-review boundary rather than a security sandbox. Their public
constructors do not accept arbitrary protocol-compatible output ports. Static
dependency checks prohibit domain/application/production infrastructure from
importing simulation and prohibit simulation from importing
`custom_components`. Passive Shadow input mirroring is one-way and immutable.

Resource limits are explicit: maximum virtual duration, timeline events,
same-time transitions, retained trace records, report size, and exploration
runs. A limit produces an explainable result and never falls back to partial
control execution.

Scenario files and reports must exclude secrets, arbitrary service payloads,
and unredacted user data. Import validation rejects unknown executable hooks;
scenario documents are data, never code.

## Future module support

The simulation kernel remains unchanged as modules add adapters:

| Module | Example virtual inputs | Example recording outputs |
|---|---|---|
| Heating | temperatures, availability, reported source/actuator state, operating mode | source permission and heat-delivery requests |
| Smart Charging | vehicle connection, state of charge, tariff, user departure request | charge enable/current/power requests |
| Lighting | occupancy, illuminance, user scene action, device availability | light/scene commands |
| Water Safety | leak, flow, valve report, sensor failure | shutoff and alarm intents |
| Security | contact/motion reports, arming action, device failure | arm/alarm/siren intents |
| Media Control | presence, user playback action, device availability | playback, routing, and volume intents |

These examples are behavioral interfaces, not physical models. A charging
command does not calculate battery chemistry; a light command does not model
room illuminance; a valve command does not prove water flow stopped.

## Smallest useful implementation after approval

The first implementation should contain only:

1. a shared production-neutral runtime assembly contract used by real and
   simulated outer composition roots;
2. scenario-v1 immutable model, YAML authoring import, and canonical normalized
   JSON export/hash with resolved effective configuration;
3. isolated environment provenance, run identity, recording ports, and Shadow
   trace sink;
4. virtual aware clock and deterministic one-shot scheduler with versioned
   ordering and distinct scheduled/delivery/evidence timestamps;
5. serialized scenario timeline runner;
6. explicit heating module adapter using existing `ControlRuntime` public
   boundaries and the shared assembly contract;
7. virtual temperature/reported-state providers and a recording source port
   with explicit success/failure behavior; actuator recording is deferred until
   an adapter actually wires it;
8. runtime start/stop and simple cold-restart timeline events, without Home
   Assistant supervisor/reload emulation;
9. a small fixed assertion set and immutable test report;
10. replay with a semantic trace fingerprint.

Passive Shadow comparison, Automated Exploration, late/cancelled-callback fault
injection, and cross-version migration tooling should follow after the scenario
runner and replay contract are proven deterministic. No UI, database, physics
model, generic plugin discovery, distributed runner, automatic remediation,
adaptive configuration, or multi-module orchestration belongs in the first
implementation.

## Architectural acceptance criteria

The foundation is acceptable when tests prove that:

- the same runtime policy code is used in real and simulated composition;
- the shared assembly contract prevents real and simulated runtime wiring from
  drifting;
- simulation packages are absent from domain/application/production
  infrastructure imports, and simulation does not import Home Assistant code;
- no simulation run can call a real effectful port;
- REAL and SHADOW_SIMULATION outputs cannot share writable production sinks;
- virtual clock and same-time ordering are deterministic;
- scenario export followed by import/replay preserves the semantic trace
  fingerprint and assertion outcomes;
- delivery time and observation/evidence time remain distinct in canonical
  scenarios and traces;
- command success never fabricates reported or physical state;
- unknown/unavailable evidence remains explicit;
- restart reconstructs only contractually supplied state;
- every exported record identifies `REAL` or `SHADOW_SIMULATION`;
- a generated failure can be replayed from its saved scenario without the
  generator;
- existing production control tests remain unchanged and green.
