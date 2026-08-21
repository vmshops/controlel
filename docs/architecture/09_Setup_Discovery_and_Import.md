# Setup, Discovery, and Configuration Import

Status: Architecture proposal

## Purpose

Controlel needs a programmatic setup foundation before it needs a graphical
wizard. The foundation discovers what a host can provide, helps a user form a
configuration, validates that configuration, and activates one explicit
immutable revision. A future UI is only a client of this lifecycle.

The foundation is module-neutral. Heating supplies the first module contract;
Smart Charging, Lighting, Water Safety, Security, and Media must be able to use
the same discovery, draft, validation, activation, and import/export lifecycle
without depending on heating types.

The central safety rule is:

> Discovery, recommendation, editing, viewing, validation, and import never
> change active control. Only an explicit activation operation may replace an
> effective active configuration.

## Existing architecture to preserve

The current Home Assistant integration is intentionally small: one config
entry builds one zone, one primary temperature sensor, and one shared heat
source. It already establishes several contracts that setup must evolve rather
than duplicate:

- `SensorId` is stable observation identity and `ZoneId` is stable logical zone
  identity. They are stored in config-entry data and cannot be overridden by
  mutable options.
- Home Assistant `entity_id` values are adapter locators. Current
  `HomeAssistantSensorBinding`, heat-source service bindings, and heat-delivery
  bindings use them, but they are not suitable as the only long-lived source
  identity because Home Assistant permits renaming them.
- `HomeAssistantIntegrationConfig` is the current immutable effective
  configuration. It is reconstructed from config-entry data plus options and
  validated before runtime construction.
- Reconfiguration unloads and reconstructs the complete runtime. Domain
  repositories are not mutated while control is running.
- `ControlRuntimeAssembly` is the production-neutral runtime construction
  boundary shared by REAL and SHADOW compositions.
- Diagnostics expose only allowlisted, privacy-minimized configuration fields.
  A discovery snapshot must not accidentally widen that diagnostic surface.

The setup foundation does not replace `Sensor`, `Zone`, `SensorId`, `ZoneId`,
capability objects, application ports, or runtime assembly with setup-specific
versions. A heating configuration compiler maps a validated canonical heating
configuration to those existing objects and inputs. During a transition from
the current config-entry format, one deterministic legacy converter creates a
canonical revision with retained source provenance. After conversion the
runtime reads only the selected canonical revision. It never merges canonical
content with legacy config-entry data or options.

`CanonicalConfigurationRevision` is the sole persisted normalized
configuration authority. A Home Assistant config entry becomes only the
integration lifecycle handle and storage location for the active-reference
identity. `HomeAssistantIntegrationConfig` remains useful as a transient,
derived adapter/runtime input; it is not independently editable or
authoritative.

## Goals

- Read floors, areas, devices, entities, relationships, and relevant endpoint
  capabilities from Home Assistant without mutating Home Assistant or Controlel
  configuration.
- Preserve provider identity and provenance separately from mutable names and
  current locators.
- Keep discovered data, recommendations, user drafts, validation results,
  canonical revisions, and effective active configuration distinct.
- Save, reopen, edit, and delete incomplete drafts.
- Explain recommendations and validation failures with stable reason codes and
  structured evidence.
- Require explicit user confirmation for important control and measurement
  bindings.
- Export and import a versioned canonical configuration suitable for backup,
  diagnostics, migration, and explicit adaptation for Shadow Runtime.
- Detect rename, disappearance, replacement, relationship, and capability
  drift without silently destroying or changing user choices.

## Non-goals

This proposal does not define or implement:

- a graphical wizard, frontend panel, or dashboard;
- AI mapping or an AI dependency;
- a generic plugin system or runtime-loaded module setup extensions;
- a multi-site wizard or distributed configuration service;
- a complete Home Assistant registry adapter;
- schemas for every future module;
- automatic repair, activation, or replacement of bindings;
- a general migration engine or deployment automation;
- live mutation of running domain repositories;
- Shadow scenarios, virtual devices, or Passive Shadow execution.

## Composition and dependency boundaries

Setup is an application workflow, not a control-domain concept. The intended
dependency direction is:

```text
future setup UI / CLI / import endpoint
                |
                v
provider-neutral setup application services
  |             |                    |
  |             |                    +--> draft/configuration repositories
  |             +--> reviewed module setup contract (heating first)
  +--> discovery and source-resolution ports
                ^
                |
Home Assistant read-only discovery and persistence adapters

explicit activation
        |
        v
module configuration compiler -> existing domain objects and runtime assembly
```

Provider-neutral workflow models and services belong in a future
`controlel.application.setup` package. Canonical configuration contracts may
extend `controlel.application.configuration`; they must not create a second
set of runtime domain entities. Home Assistant implementations remain in the
outer `custom_components/controlel` adapter. Neither the domain nor ordinary
runtime imports Home Assistant setup code.

The shared setup kernel does not import `SensorId`, `ZoneId`, heating commands,
or any other module-specific type. It carries opaque module identity and a
typed payload owned by the selected module adapter. The Heating setup adapter
alone translates its logical identities to the existing `SensorId`, `ZoneId`,
`Sensor`, `Zone`, heat-delivery, and source-control configuration contracts.
Domain and control application services never depend on setup lifecycle types,
discovery snapshots, recommendations, drafts, or validation reports.

The active runtime receives only a compiled immutable effective configuration
and concrete ports. It cannot query a draft repository or discovery provider.
This is the enforcement boundary that prevents merely viewing or editing setup
from changing control.

## Discovery boundary

### Read-only contract

A `StructureDiscoveryPort` returns an immutable `DiscoverySnapshot`. It has no
create, update, delete, service-call, registry-write, or activation methods.
The Home Assistant adapter reads only the floor, area, device, and entity
registries plus the minimum state/capability metadata required for setup.

The snapshot contains:

- provider type and stable provider-instance identity;
- snapshot identity, aware `captured_at`, adapter contract version, and content
  fingerprint;
- normalized floors, areas, devices, and entities;
- their provider-native references and relationships;
- observable and controllable endpoint descriptions;
- advertised classes, units, supported features, and availability evidence;
- current display names and locators as presentation metadata.

Discovery describes structure and advertised capability. It does not prove a
device is physically present, that a measurement is correct, or that a command
will succeed. A discovered control endpoint is never exercised during
discovery.

Snapshots are complete immutable observations at one time. Refresh produces a
new snapshot; it does not mutate an older snapshot or any configuration. v0.1
may refresh explicitly. Registry-change subscriptions and background drift
monitoring can be added later without changing this contract.

### Stable provider references

Long-lived bindings use a `ProviderObjectReference` with at least:

- `provider`: for example `home_assistant`;
- `provider_instance_id`: identity of the Home Assistant installation or other
  environment;
- `object_kind`: provider-qualified object kind; v0.1 Home Assistant uses floor,
  area, device, entity, and endpoint;
- `native_id`: the provider's primary registry identity when one exists;
- `identity_quality`: `STABLE` or `EPHEMERAL`;
- optional parent reference for an endpoint owned by another object.

For Home Assistant v0.1, identity and recovery evidence are explicit:

| Object | Primary identity | Recovery/context evidence | Locator/presentation only |
| --- | --- | --- | --- |
| HA environment | Home Assistant core instance ID | import/backup provenance | instance name or URL |
| Entity | entity-registry entry ID | entity domain, platform, integration `unique_id`, `previous_unique_id`, config-entry/subentry and device association | `entity_id`, names and aliases |
| Device | device-registry ID | integration-provided identifiers and connections, config-entry association | device name, model and area |
| Area | area-registry ID | prior snapshot provenance | name, aliases and floor membership |
| Floor | floor-registry ID | prior snapshot provenance | name, aliases and level |
| Endpoint | owning stable object reference plus module/provider endpoint key | advertised capability/service evidence | current service or state locator |

The current `entity_id` is always a locator, never the sole stable identity.
An exact entity-registry ID match may automatically resolve a renamed
`entity_id`; this changes no user selection. Integration reload normally keeps
registry identities and resolves the same way.

If the primary registry object disappeared, a match on `unique_id`, platform,
device identifiers, connections, config-entry association, name, or topology
is recovery evidence only. Registry recreation, integration recreation, and
device replacement create recovery/replacement candidates. They do not prove
identity continuity and cannot silently replace an important measurement or
control binding. A unique strong match is explainable and rankable, but v0.1
still requires explicit confirmation before creating a new binding reference.
Ambiguous matches remain unresolved.

Some entities may not have a registry identity. The adapter may expose them as
`EPHEMERAL`, retaining their current locator and explaining the limitation. It
must not fabricate a stable identity from a mutable name. A module may reject
an ephemeral reference for an important binding or require explicit user
confirmation. Custom service targets without a registered owning object are
also `EPHEMERAL` and cannot promise rename recovery.

Provider identity is environment-scoped. An entity-registry identity exported
from one Home Assistant installation cannot be assumed to identify an object
in another installation.

A Home Assistant area is not automatically a Controlel zone, an entity is not
automatically a Controlel sensor, and a device is not automatically an
actuator. Discovery preserves provider structure; a module adapter plus an
explicit draft selection creates the relationship to existing Controlel
logical identities.

The shared kernel treats provider object kinds and topology relationships as
namespaced values. It does not require every provider to implement Home
Assistant's floor/area/device hierarchy or define a universal building/device
ontology.

### Candidates and capabilities

A `SetupCandidate` is a module-generated role candidate centered on one
discovered object or endpoint. It may reference supporting device/area/floor
evidence, but v0.1 does not build composite candidate graphs. It contains a
stable candidate ID within its discovery snapshot, references to the underlying
objects, normalized capability names, and the evidence from which those
capabilities were classified.

Candidate IDs are snapshot-local navigation aids. A draft never persists a
candidate ID as its binding; it persists the selected provider reference and
the provenance of that selection.

Shared capability vocabulary should remain small and behavioral, for example:

- `measurement.temperature`;
- `state.binary`;
- `command.enable_disable`;
- `command.target_temperature`.

Module adapters decide whether a candidate satisfies a module role. The shared
foundation must not grow a universal device ontology. Home Assistant-specific
details such as domains, device classes, state classes, supported-feature
flags, and services remain structured classification evidence rather than
leaking Home Assistant objects into the core contract.

Command capability and reported-state capability remain separate. Discovering
an enable service does not imply that a reported source-state endpoint exists,
and command success never becomes reported or physical state.

## Setup artifacts and lifecycle

The familiar `DISCOVERED -> PROPOSED -> DRAFT -> VALIDATED -> ACTIVE` sequence
is useful as a user-facing lifecycle, but it must not be implemented as one
mutable record. Each stage is a distinct artifact with different authority:

```text
DiscoverySnapshot --derive--> RecommendationSet
        |                         |
        +----------select--------+
                                  v
                         SetupDraft revision N
                                  |
                         normalize + validate
                                  v
                         ValidationReport
                                  |
                       if activation-ready
                                  v
                 immutable configuration revision
                                  |
                       explicit activate command
                                  v
                       persisted ActivationAttempt
                         /                   \
              success /                     \ failure/interruption
                     v                       v
          atomic ActiveReference       deterministic rollback
                     |                       |
          loaded-runtime stamp     previous revision remains selected
```

### Lifecycle semantics

- **Discovered** means only that a provider object was observed in a snapshot.
  It is not configured.
- **Proposed** means that deterministic recommendation rules ranked a candidate.
  A proposal is not a user choice and is never active.
- **Draft** is a durable, user-owned revision. It may be incomplete or contain
  references that are currently unresolved. Saving a draft performs no
  activation.
- **Validated** describes one exact draft revision evaluated against declared
  schema, module contract, provider evidence, and confirmation requirements. A
  validation report is evidence, not an active state. Editing the draft creates
  a new revision and makes the earlier report inapplicable.
- **Canonical revision** is an immutable normalized revision produced only
  from an activation-ready validation result. It may remain inactive, be
  exported, or later be selected for activation.
- **Activating** means a persisted activation attempt is applying one inactive
  candidate while retaining the previous/last-known-good revision.
- **Active** means that one immutable canonical configuration revision is the
  explicit effective selection for one module instance. Activation is not a
  property copied onto a draft.

Thus discovered is not configured, configured is not necessarily valid, valid
is not active, a canonical revision may be inactive, and incomplete
configuration can be saved but cannot produce an activation-ready canonical
revision.

A draft has stable `draft_id`, module and module-instance identity, monotonically
increasing revision, creation/update timestamps, optional base active revision,
binding selections, module-specific settings, and explicit confirmations.
Read operations return immutable snapshots. They never fill defaults, refresh
aliases, accept recommendations, revise timestamps, or otherwise persist.

A binding deliberately separates four provenance dimensions:

- `BindingSelection` records the module role, selected
  `ProviderObjectReference`, selection origin (`MANUAL`,
  `RECOMMENDATION_ACCEPTED`, `IMPORTED`, `MIGRATED`, or
  `CLONED_FROM_ACTIVE`), aliases visible at selection time, and source
  discovery/import/migration evidence.
- `BindingConfirmation` records the confirming actor, time, exact draft
  revision, exact reference, and the recommendation or recovery candidate that
  was accepted. An imported or migrated record does not fabricate a new user
  confirmation.
- revision lineage records the parent configuration and import/migration
  derivation.
- `ReferenceResolutionEvidence` records how the unchanged reference resolved:
  exact registry ID, current locator, ephemeral locator, missing, ambiguous, or
  recovery candidate.

Automatic exact-ID resolution is not a selection and does not change selection
origin or confirmation. Accepting a registry-recreation or replacement
candidate creates a new draft revision and confirmation. These distinctions
preserve where a binding came from without making mutable aliases part of its
identity.

Deleting an incomplete draft deletes only that draft. Editing an active setup
first creates a new draft based on the active revision. Deactivating or deleting
an active setup is a separate explicit lifecycle operation and is not implied
by draft deletion.

## Recommendation model

Recommendations are deterministic, transparent setup assistance. A
`RecommendationSet` is tied to one discovery snapshot, module contract
version, and recommendation-policy version. Each role recommendation contains:

- the module-defined role key;
- one optional recommended candidate and ordered alternatives;
- qualitative confidence (`LOW`, `MEDIUM`, or `HIGH`) rather than false numeric
  precision;
- stable reason codes;
- references to supporting discovery evidence;
- whether explicit confirmation is required.

Examples of evidence are matching temperature device class and unit, shared
area membership, or an advertised enable/disable service. Display names may be
weak ranking evidence but never stable identity.

Accepting a recommendation is an explicit draft edit. Important bindings such
as a primary measurement, controllable source, charger, water shutoff, security
device, or media command endpoint require explicit confirmation even when the
recommendation has high confidence. The confirmation records the chosen stable
source reference, draft revision, recommendation/snapshot provenance when
applicable, and confirmation time.

There is no AI dependency, hidden learning, automatic activation, or silent
replacement.

Recommendation and validation policy versions are fixed contract constants in
v0.1. They are recorded for reproducibility but do not require a policy
registry, plugin mechanism, or dynamically selectable engine.

## Configuration authority and representations

The architecture deliberately separates artifacts and assigns exactly one
authority at each stage:

| Artifact | Authority | Explicitly not authoritative for |
| --- | --- | --- |
| `DiscoverySnapshot` | What the provider adapter observed at `captured_at` | User intent or configuration |
| `RecommendationSet` | No configuration authority; deterministic advice only | A binding choice or confirmation |
| latest `SetupDraft` revision | Current editable user intent for that draft | Normalized or active configuration |
| `ValidationReport` | Assessment of one exact draft/canonical fingerprint and provider-resolution generation | Configuration content or activation |
| `CanonicalConfigurationRevision` | Sole persisted normalized configuration content | Active selection unless referenced by `ActiveReference` |
| `ActiveReference` | Desired selected canonical revision, generation, fingerprint, and committing operation ID for one environment/module instance | Runtime health or proof that a runtime loaded |
| `ActiveConfigurationHealth` | Current resolution and validation health of the selected revision | Selection or configuration mutation |
| `LoadedRuntimeConfiguration` stamp | Revision ID and semantic fingerprint actually loaded by the current runtime | A separately editable configuration |
| Home Assistant config entry | Integration lifecycle handle and active-reference storage | Module settings, drafts, or legacy option merging |

`EffectiveModuleConfiguration` is a transient typed projection compiled from
one canonical revision plus current adapter resolution. It is stamped with the
canonical revision ID and semantic fingerprint. When a runtime starts
successfully, the same stamp becomes `LoadedRuntimeConfiguration` evidence.
Neither projection is persisted or edited as another normalized model.

Only an effective projection from the selected or explicitly activating
canonical revision is supplied to runtime composition. Discovery,
recommendation, draft editing, validation, import, and viewing cannot alter an
active reference, loaded-runtime stamp, or running runtime.

Normalization is pure and deterministic. All defaults that affect behavior are
materialized in the canonical module payload. Presentation aliases and
recommendation evidence do not become runtime settings. Adapter resolution may
map a stable source reference to its current `entity_id` at startup without
changing the stored user choice.

For heating, the Heating adapter compiles its typed payload into existing
`SensorId`, `ZoneId`, `Sensor`, `Zone`, source and heat-delivery bindings, and
`ControlRuntimeAssembly` inputs. It does not construct a setup-specific
heating controller. The current `HomeAssistantIntegrationConfig` can serve as
the transient adapter-effective type, but its fields are derived wholly from
one canonical revision and current reference resolution. Runtime construction
must never overlay config-entry options or legacy values on that projection.

## Core data contracts

The smallest shared contract set is:

- `ProviderInstanceId` and `ProviderObjectReference`;
- `DiscoverySnapshot`, `DiscoveredObject`, and `DiscoveredEndpoint`;
- `SetupCandidate` and `RecommendationSet`;
- `SetupDraft`, `DraftRevision`, `BindingSelection`, and `BindingConfirmation`;
- `CanonicalConfigurationRevision`, `ActiveReference`,
  `ActiveConfigurationHealth`, and `LoadedRuntimeConfiguration`;
- `ActivationAttempt` and `ActivationResult`;
- `ValidationIssue` and `ValidationReport`;
- `ConfigurationImportResult` and immutable export metadata.

All validated contracts are deeply immutable. Nested evidence uses immutable
tuples and mappings or immutable JSON values; callers cannot change a validated
snapshot, report, or canonical revision by retaining a mutable dictionary.
Identifiers are non-empty and timestamps are timezone-aware. Evidence and
reason codes are JSON-safe and machine-readable.

Every canonical revision carries the minimum lineage needed for future
configuration history:

- optional parent revision ID;
- aware creation timestamp;
- actor/source identity and change-source kind;
- stable change reason and bounded context;
- envelope and module schema versions;
- Controlel core and Home Assistant integration versions used to create it;
- import source document hash or migration identifier/from-version/to-version
  when applicable.

Immutable parent and child revisions allow a future history projector to
derive previous value, new value, and canonical unit. v0.1 does not store a
second field-level change log or build a history query engine.

The shared layer does not define arbitrary module fields, a schema DSL, a
generic property bag interpreted at runtime, or a plugin registry. Each module
owns a typed payload and contract version inside the common canonical envelope.

Setup does not introduce another event bus. Setup operations return structured
application results and store revision/audit provenance. If activation needs
runtime-visible telemetry later, the host projects it through the existing
operational-event boundary; discovery and draft reads emit no control events.

## Home Assistant adapter boundary

The outer Home Assistant adapter supplies:

- `HomeAssistantDiscoveryAdapter`, which reads registry structure and returns a
  normalized snapshot;
- `HomeAssistantReferenceResolver`, which reports `RESOLVED`, `EPHEMERAL`,
  `MISSING`, `RECOVERY_CANDIDATE`, `AMBIGUOUS`, or `ENVIRONMENT_MISMATCH`
  without changing a binding. Recovery matching is an internal adapter concern;
  candidate results remain structurally separate from resolved references and
  always require later confirmation;
- draft and canonical-configuration repository implementations;
- persisted activation-attempt storage and a host activation adapter that can
  construct a candidate from an explicit canonical revision and roll back to
  the last-known-good revision;
- module-specific binding compilation from stable references to current Home
  Assistant measurement subscriptions and service-call targets.

The discovery and resolver interfaces are separate. Discovery answers “what is
available in this snapshot?” Resolution answers “what does this already chosen
stable reference resolve to now?” This allows rename recovery without treating
every rediscovery as configuration editing.

Home Assistant state values are transient evidence. Registry structure,
advertised capability, current availability, and live measurements remain
separate. Neither discovery nor resolution calls a Home Assistant service.

The limited Heating milestone reads only entity-registry-advertised domain,
device class, original device class, unit, and supported-feature flags for
candidate classification. It does not read entity state. Heating recommends
temperature measurements, simple source switches, supported climate target
actuators, and reported source state only where the existing simple controlled
switch path can consume it. Arbitrary external service targets remain
selectable as explicitly unverified alternatives; they require confirmation
and produce a validation warning rather than an invented capability claim.

The provider-instance identity prevents imported REAL bindings from being
silently resolved against another Home Assistant installation or a Shadow
environment. Diagnostics continue to use explicit allowlists/redaction rather
than serializing raw discovery snapshots, registry identifiers, or imported
documents.

The Home Assistant config entry stores only the Controlel environment/module
instance identity and `ActiveReference` (plus Home Assistant's own lifecycle
metadata). Drafts, normalized fields, legacy options, discovery content, and
runtime state are not parallel config-entry authorities. Existing legacy data
and options remain readable only by the one-way legacy converter; canonical
runtime setup never calls the legacy merge path.

## Module-extension boundary

A reviewed, explicitly composed `ModuleSetupAdapter` owns setup semantics for
one module contract version. It provides:

- stable module and role identifiers;
- candidate filtering/classification for those roles;
- deterministic recommendation rules and reason codes;
- typed draft normalization;
- structural, required-binding, capability, and module-specific validation;
- compilation of a valid canonical payload to that module's existing
  configuration boundary.

The setup coordinator treats module payloads as versioned typed values and
does not interpret their fields. Module adapters are selected explicitly in
the composition root. v0.1 does not scan packages, load third-party code, or
define a plugin protocol.

Shared setup code may validate source-reference structure, artifact identity,
revision matching, and import envelopes. It must not decide that a temperature
sensor is sufficient for heating, that a switch is a charger, or that an area
contains a security perimeter; those rules belong to the relevant module.

The first heating adapter should expose only roles supported by today's
runtime, such as primary zone temperature, shared source command endpoint,
optional reported-source state, and optional heat-delivery actuator. It must
preserve the existing Zone / Heat Delivery / Source Control boundaries and
must not infer physical state from command capability.

The Heating adapter must preserve both existing source-control modes. Standard
switch enable/disable remains a convenience normalization, while arbitrary
enable and disable service domain/name/target bindings remain lossless typed
configuration. A registered service target uses its stable provider reference
and resolves to the current target locator. An unregistered or non-entity
target is explicitly `EPHEMERAL`. The setup foundation must not reduce current
custom-service support to simple switch entities.

Future modules implement the same lifecycle while owning different roles and
typed payloads:

| Module | Example module-owned roles |
| --- | --- |
| Heating | zone measurement, heat delivery, shared source |
| Smart Charging | vehicle/charger state, charging command, tariff context |
| Lighting | light state/command, occupancy context |
| Water Safety | leak measurement, shutoff command/state |
| Security | contact/motion observations, arming endpoint |
| Media | player state, playback/volume endpoints |

These examples do not add the roles to the shared setup vocabulary.

## Validation model

Validation returns a `ValidationReport`, never only a boolean. Each
`ValidationIssue` contains:

- stable issue code;
- severity (`ERROR`, `WARNING`, or `INFO`);
- configuration path and optional module role;
- related stable source reference when applicable;
- message key plus safe structured parameters;
- evidence references and suggested user action where known.

The report records draft/canonical revision, discovery snapshot and resolution
generation, module contract and validator-policy versions, validation time,
issues, and activation readiness.

Validation runs in explicit stages:

1. **Structural validation** checks envelope and typed module schema, values,
   cardinality, identity uniqueness, and deterministic defaults.
2. **Required-binding validation** checks that every module-required role has a
   user selection and required confirmation.
3. **Capability validation** checks the selected endpoint evidence against the
   module role contract while preserving command/observation separation.
4. **Referential validation** resolves stable provider references and reports
   missing, ambiguous, environment-mismatched, or ephemeral bindings.
5. **Activation readiness** combines blocking issues, confirmation state,
   supported versions, and final module preconditions.

An unknown, unavailable, or temporarily missing provider object is not silently
converted to false or deleted. A stale discovery snapshot is reported. Warnings
do not block unless a documented module rule makes that condition unsafe;
errors block activation.

Immediately before canonicalization, the coordinator re-reads the exact draft
revision and performs a final validation pass. If the draft changed, it returns
a structured stale/conflict result and creates no canonical revision. Before
activation, it instead re-reads the immutable canonical revision and performs
fresh referential/capability/readiness validation. It never executes mutable
draft content or applies an older validation report to newer content.

Validation failure retains the draft and all user selections unchanged. An
activation-ready report permits a pure canonicalization operation to persist
one inactive `CanonicalConfigurationRevision`; canonicalization still does not
activate it. Later drift produces a new `ActiveConfigurationHealth` assessment
for an active revision and never rewrites that revision or `ActiveReference`.

## Activation and safety boundary

Activation is an explicit command containing an inactive canonical revision
ID, its semantic fingerprint, the expected current `ActiveReference`, and the
expected current resolution/validation generation. It does not accept a
mutable draft as executable input.

One persisted `ActivationAttempt` contains:

- stable attempt ID and timestamps;
- candidate revision ID and semantic fingerprint;
- previous selected revision and last-known-good revision;
- expected active-reference revision for compare-and-swap;
- current state and structured failure/rollback evidence;
- candidate and rollback loaded-runtime stamps when available.

Its states are:

- `PREPARED`: candidate is validated, compiled without effects, and durably
  staged; the previous runtime and `ActiveReference` remain unchanged.
- `APPLYING`: the serialized host lifecycle is replacing the runtime. No other
  activation may proceed.
- `COMMITTED`: candidate startup reached the documented active boundary and
  the `ActiveReference` was atomically changed to the candidate; the candidate
  becomes the new last-known-good revision.
- `ROLLED_BACK`: candidate application failed or was interrupted and the
  previous/last-known-good runtime was reconstructed successfully.
- `FAILED`: the candidate was not committed and deterministic rollback could
  not restore a usable runtime. The previous revision remains authoritative;
  runtime health is explicitly unavailable/failsafe.

The normal sequence is:

1. re-read and validate the inactive canonical candidate and current provider
   resolution;
2. compile its effective configuration without touching the runtime;
3. persist `PREPARED` with the previous and last-known-good revisions;
4. transition to `APPLYING` and use the existing complete serialized
   unload/reconstruction lifecycle, ensuring that only one runtime owns command
   authority;
5. after candidate startup succeeds, atomically compare-and-swap
   `ActiveReference`, including the candidate revision/fingerprint, new
   generation, and committing attempt ID;
6. persist the candidate loaded-runtime stamp and terminal `COMMITTED` result,
   and expose success only after that result is durable.

“Candidate startup succeeds” is an adapter-defined but explicit readiness
boundary, not successful object construction. For Home Assistant it requires
the host initialization/startup-recovery sequence, initial provider evidence,
required subscriptions/ports, and required config-entry platform setup to
complete without fatal setup failure. The adapter returns one
`CandidateRuntimeReady` result containing the loaded revision/fingerprint;
only that result permits the active-reference compare-and-swap.
Candidate construction receives that explicit effective configuration and must
not re-read config-entry options or the still-previous `ActiveReference` while
the attempt is `APPLYING`.

The durable write order is candidate startup evidence, one atomic
active-reference compare-and-swap carrying the attempt ID, then terminal
`COMMITTED`. The active-reference write is the sole commit point. A candidate
whose startup or reference comparison failed never appears in
`ActiveReference` and therefore never becomes active.

If interruption occurs after the reference swap but before the terminal
attempt write, recovery compares the non-terminal attempt with
`ActiveReference.committing_operation_id`. For activation, that value is the
activation-attempt ID. A matching candidate reference proves
that commit occurred; recovery finalizes `COMMITTED` and loads that active
revision through normal startup. A missing or non-matching marker proves that
commit did not occur; recovery retains/restores the recorded previous reference
and performs rollback. This makes recovery deterministic despite Home
Assistant config-entry and integration-owned storage not sharing one database
transaction.

If validation, resolution, compilation, or the initial expected-reference check
fails before `APPLYING`, no runtime or active reference changes. If candidate
reconstruction/startup fails, or if the final compare-and-swap unexpectedly
fails after candidate startup, the candidate is stopped. The host then
reconstructs the revision selected by the authoritative current reference,
using the recorded previous/last-known-good revision when that reference is
unchanged. Successful restoration records `ROLLED_BACK`. If restoration also
fails, the attempt records `FAILED`; the authoritative non-candidate revision
remains selected while runtime health reports unavailable/failsafe through the
existing host failure boundary. A failed candidate never becomes active.

On process interruption, startup inspects any non-terminal attempt. `PREPARED`
is abandoned without runtime change unless the matching commit marker exists.
`APPLYING` is never assumed successful from attempt state or prior startup
evidence alone: only a matching atomic active-reference marker proves commit.
Without that marker, the recorded previous active reference is retained or
restored, then the host performs ordinary shutdown/recovery semantics and
reconstructs the last-known-good revision before recording `ROLLED_BACK` or
`FAILED`. Candidate startup alone never promotes a revision.

Activation is atomic from the user's configuration perspective: the operation
ends with either the candidate durably selected and loaded, or the previous
revision selected with an explicit rollback/failure result. External service
calls already dispatched during startup cannot be made transactional or
inferred to have changed physical state; their command outcomes remain retained
evidence and startup recovery/reconciliation remains authoritative.

The Home Assistant v0.1 implementation retains complete runtime
unload/reconstruction. It must not mutate `ZoneRepository`, source policy, or
ports in place, and rollback compiles only from the retained canonical revision.

Draft save, recommendation acceptance, import, validation, discovery refresh,
and viewing are never aliases for activation. There is no automatic apply on a
read, page transition, or successful validation.

## Rename, disappearance, replacement, and later editing

Rediscovery reconciles objects by `ProviderObjectReference`, not display name or
current `entity_id`:

- **Rename:** the stable reference resolves and the discovery view shows the
  new alias. The stored binding and module-owned logical identity stay
  unchanged. Resolving the new runtime locator by exact registry ID is not a
  configuration mutation; the resolution evidence records the locator change.
- **Disappearance:** the selection remains in the draft or active canonical
  revision and `ActiveConfigurationHealth` reports it unresolved. It is not
  deleted and no replacement is activated automatically.
- **Registry or integration recreation:** secondary identity evidence may
  identify a strong recovery candidate, but the primary identity discontinuity
  remains visible. Important bindings require a new confirmed draft selection.
- **Replacement:** likely replacements may be recommendations with explicit
  evidence. Selecting one creates a new draft revision and records old/new
  provenance. Active control keeps its prior revision until explicit
  activation.
- **Capability change:** current health and validation report the missing or
  altered capability. Neither the canonical revision nor active reference is
  rewritten. A compatible replacement or changed role selection follows the
  ordinary draft/validation/activation lifecycle.
- **Area/floor change:** relationships and labels update in discovery. A module
  may warn or revise future recommendations, but the movement does not rewrite
  a confirmed binding.
- **Later module edit:** the active canonical revision is copied to a new
  draft. Repeated edits and validation leave the active revision untouched.

For an already active configuration, runtime handling of an unavailable or
missing live endpoint remains the responsibility of existing measurement,
source recovery, failure, and safety behavior. Setup drift reporting must not
pretend that a missing endpoint is a control decision.

v0.1 resolves locators during discovery, validation, activation, and runtime
construction. It does not hot-swap a running subscription or command port in
response to registry events. Continuous drift monitoring and a serialized
same-identity live rebind lifecycle are deferred. Until then, an in-operation
rename or disappearance follows existing unavailable/dispatch-failure safety
behavior and is resolved on the next explicit reconstruction.

## Persistence and import/export

### Repository responsibilities

Persistence is separated by authority:

- discovery snapshots are replaceable, bounded observations;
- drafts are durable mutable-by-revision user work;
- canonical configuration revisions are immutable;
- one active reference selects a canonical revision for a provider environment,
  module, and module instance;
- activation attempts are durable transactions until `COMMITTED`,
  `ROLLED_BACK`, or `FAILED`.

Repository operations use optimistic revision checks. Saving produces a new
draft revision; it does not mutate an object already returned to a caller.
Only canonical revisions contain normalized settings. The integration-owned,
versioned persistence adapter stores drafts, canonical revisions, lineage, and
activation attempts. The Home Assistant config entry stores only the
environment/module-instance lifecycle identity and `ActiveReference`. Runtime
setup resolves that reference and compiles exactly that canonical revision.

Legacy config-entry data/options have one permitted use: the deterministic
one-way legacy converter. Before conversion it retains an exact source snapshot
and hash as a pre-conversion backup, normalizes the effective legacy entry once,
validates it, and creates one canonical revision with `MIGRATED` provenance,
source schema/integration versions, and migration identifier. The config entry
switches atomically to canonical `ActiveReference` form only after the
conversion artifact is durable and compilable. After that switch, legacy
settings are archived provenance and are never merged into runtime
configuration. Failure leaves the legacy entry and backup unchanged and
reports a structured migration/setup issue; it never creates partial dual
authority.

This bootstrap conversion is permitted only when the canonical semantic
fingerprint is equivalent to the previously effective legacy configuration. It
changes representation, not user intent or control semantics. Any conversion
that would introduce a behavioral default or change a binding produces a
non-active draft requiring ordinary validation, confirmation, and explicit
activation.

### Canonical configuration envelope

The export authority is deterministic canonical JSON. A v1 envelope contains:

- envelope `schema_version`;
- stable configuration ID and immutable revision;
- provider type and provider-instance binding scope;
- module key, module-instance ID, and module contract/schema version;
- parent revision, created-at, actor/source, reason, and provenance metadata;
- stable logical Controlel identities;
- confirmed source bindings with provider references;
- complete normalized module payload with behavior-affecting defaults
  materialized;
- schema/module/core/integration versions plus import/migration lineage;
- canonicalization policy version, document hash, and semantic fingerprint.

Canonicalization v1 defines:

- UTF-8 JSON with deterministic object-key ordering and no dependence on input
  YAML/JSON formatting;
- aware timestamps normalized to UTC with a canonical `Z` representation;
- durations represented in the module schema's explicit canonical duration
  unit, with v0.1 using seconds for existing Controlel duration settings;
- temperatures and other quantities represented in module-declared canonical
  units, with v0.1 Heating using degrees Celsius;
- finite normalized numeric representation and rejection of NaN/infinity;
- deterministic ordering for semantically unordered sets such as identifiers,
  connections, aliases, and labels, while preserving order where order is
  meaningful;
- every behavior-affecting default materialized before hashing.

The document hash covers the exact canonical revision body, including lineage
and provenance but excluding the hash field itself. It proves backup/import
integrity. The semantic fingerprint covers only normalized behavior-affecting
configuration, stable logical identity, binding semantics, and relevant schema
versions. It excludes revision/storage IDs, timestamps, actors, export
metadata, presentation aliases, current locators, and transient resolution
evidence, as well as the document-hash and semantic-fingerprint fields
themselves. The inclusion/exclusion lists and algorithm are versioned.

Canonical configuration explicitly excludes measurements, live availability,
reported or commanded device state, decisions, runtime status, scheduled
deadlines, source-recovery/reconciliation state, activation session state,
debug-expiry state, diagnostics history, run IDs, and other process/session
evidence. Configured diagnostics policy remains configuration; its current
runtime expiry or observation state does not.

An export wrapper may add `exported_at`, tool versions, and redaction notes;
these do not change the immutable configuration revision. Re-exporting the
same revision yields the same canonical revision bytes, document hash, and
semantic fingerprint. Sensitive data is excluded or explicitly redacted. A
redacted diagnostic view must not be presented as an importable backup.

Envelope schema, module payload schema, and Home Assistant config-entry version
are separate version axes:

- additive optional fields or fields with deterministic defaults are backward
  compatible and retain their schema version;
- breaking semantic/type changes and renamed or removed required fields
  increment the affected schema version;
- module payload changes increment only that module contract when the envelope
  is unchanged;
- a Home Assistant config-entry version changes only when the persisted host
  layout requires it.

v0.1 implements only the explicit legacy-entry converter and otherwise defines
migration contracts and unsupported-version errors, not a general migration
engine. A future deterministic migration first retains the original canonical
document/hash as a pre-migration backup, produces a new child revision, and
records migration ID, from/to schemas, application version, timestamp,
actor/source, and outcome. Importers and migrators never guess at unknown
versions, discard unknown required data, or substitute current defaults
silently.

### Import lifecycle

Import performs parse, integrity/version checks, environment compatibility
assessment, normalization, and validation into a new draft/import result. It
never activates.

An import from another provider instance preserves the source provenance but
marks environment-bound references unresolved. The user must rebind and
confirm them. Logical Controlel IDs may be retained when valid and
non-conflicting; collisions return structured issues rather than being renamed
silently.

Import preserves any original confirmation as historical provenance; it does
not claim that the importing user confirmed the binding. A same-environment,
integrity-verified backup may retain its original confirmation evidence, but
activation is still explicit. Environment mismatch, identity discontinuity,
or changed important binding requires a new confirmation in the imported
draft.

A REAL canonical configuration is not directly executable in Shadow Runtime.
The simulation module adapter derives a Shadow effective configuration by
copying the normalized module settings and stable logical identities, then
performing one explicit REAL-to-SHADOW binding substitution to virtual provider
references. The derived artifact records the source revision/document hash,
substitution map, and `SHADOW_SIMULATION` provenance. It is a run input, not a
persisted canonical configuration authority and cannot change `ActiveReference`.
A canonical Home Assistant source reference must never resolve directly to a
simulation port, and an imported configuration must not blur REAL/SHADOW
provenance.

## Risks and architectural ambiguities

1. **Home Assistant persistence transactions.** Canonical authority and write
   ordering are defined, but Home Assistant config-entry storage and the
   integration-owned revision/attempt store are not one database transaction.
   v0.1 must test every interruption point and make attempt recovery idempotent.
2. **Home Assistant instance-ID change or cloning.** Restored backups may
   intentionally retain an instance ID, while Home Assistant can also recreate
   one. Environment mismatch must remain visible and recoverable without
   treating either case as proof of object identity.
3. **Unregistered Home Assistant entities.** Some endpoints may lack stable
   registry identity. They require explicit ephemeral-identity behavior rather
   than a fabricated guarantee.
4. **Portable versus environment-bound backup.** Module settings and logical
   IDs are portable; Home Assistant native references are not. Import must make
   this distinction visible and require rebinding.
5. **Availability versus identity loss.** Temporary `unavailable`, a missing
   registry entry, and a newly created replacement are different conditions.
   The adapter must not collapse them.
6. **Capability drift.** Integration upgrades or device replacement can change
   advertised capabilities. Active runtime safety and setup revalidation are
   separate concerns.
7. **Effectful activation.** The configuration transaction can roll back, but
   service calls already dispatched by candidate startup cannot be undone or
   interpreted as physical state. Attempt reports must retain those outcomes.
8. **Custom service targets.** Existing arbitrary service bindings may target
   entities without registry identity or future non-entity targets. Their
   explicit ephemeral behavior must remain lossless and visible.
9. **Privacy.** Registry identifiers, topology, device identifiers, and service
   targets can be sensitive. Backup export and diagnostic projection need
   different explicit policies.
10. **Cross-module resource conflicts.** Future modules may select the same
   endpoint. Cross-module ownership/arbitration is not required for heating
   v0.1 and must not be hidden inside the shared setup foundation.
11. **Config-entry granularity.** The current one-entry/one-zone host shape does
   not decide the eventual relationship among site, module instance, and config
   entry. v0.1 should keep explicit environment/module-instance IDs without
   building a multi-site coordinator.

## Minimal implementation plan for v0.1

After architecture approval, the smallest useful implementation is:

1. Add deeply immutable module-neutral provider-reference, discovery, candidate,
   recommendation, draft, validation, canonical-revision, active-reference,
   health/stamp, and activation-attempt contracts.
2. Add deterministic canonical JSON, UTC/unit/ordering normalization, document
   hashing, semantic fingerprinting, version rejection, one-revision export,
   and import into a non-active draft.
3. Add repository ports plus in-memory test implementations and the minimum
   durable Home Assistant storage for incomplete drafts, immutable revisions,
   and activation attempts. The config entry stores only `ActiveReference`.
4. Add a limited read-only Home Assistant discovery adapter for floors, areas,
   devices, registered entities, stable identity, topology, recovery evidence,
   and the minimal entity-registry-advertised capability fields used by the
   first Heating adapter. There is no live-state read, background loop, or
   registry write. Broader capability discovery remains later work.
5. Add exact registry-ID resolution with current locator, missing, ambiguous,
   environment-mismatch, and ephemeral results. Secondary identity evidence
   produces confirmation-required candidates only.
6. Add one reviewed Heating setup adapter for today's one-zone temperature,
   shared source, optional reported-source, and optional heat-delivery
   bindings, preserving arbitrary source service domain/name/target contracts.
7. Add one small deterministic recommendation path for those roles with stable
   reason/evidence codes and explicit user confirmation.
8. Add structural, required-binding, capability, referential, and readiness
   validation; successful readiness can create an inactive canonical revision.
   Failed validation leaves the draft unchanged.
9. Add save/reopen/edit/delete for incomplete drafts and clone-active-to-draft.
10. Add the deterministic one-way legacy converter with pre-conversion backup,
    source hash, validation, and migration lineage. No general migration engine.
11. Add explicit activation with persisted attempts, optimistic
    revision/fingerprint checks, existing full runtime reconstruction,
    interruption recovery, and last-known-good rollback.
12. Test read-only isolation, nested immutability, deterministic serialization,
    entity rename versus recreation, missing/replacement preservation,
    incomplete draft persistence, confirmation provenance, validation
    staleness, import-never-activates, no legacy/canonical merge, activation
    success/failure/interruption/rollback, rollback failure health, loaded
    revision stamping, and unchanged active control before explicit apply.

## Explicitly deferred

The following wait until the v0.1 contracts and heating vertical slice are
proven:

- graphical setup wizard, frontend entities, and dashboards;
- automatic discovery refresh subscriptions and continuous drift monitoring;
- AI recommendations, learned ranking, or automatic mapping;
- generic plugin discovery, third-party module loading, or a schema DSL;
- Smart Charging, Lighting, Water Safety, Security, and Media schemas/adapters;
- multi-site setup and cross-module resource arbitration;
- a general migration engine and automatic legacy migration campaign;
- automatic binding replacement or automatic activation;
- field-level configuration history/query service, rollback UI, and deployment
  orchestration beyond the required activation rollback;
- live/hot binding reconfiguration and continuous drift repair;
- Passive Shadow, automatic scenario generation from setup, or direct reuse of
  REAL provider bindings in simulation;
- broad Home Assistant registry coverage, registry writes, and device-specific
  fault libraries.

The v0.1 success criterion is deliberately narrow: one incomplete heating
draft can be discovered, recommended, saved, reopened, validated, exported,
imported as a non-active draft, and explicitly activated into the existing
runtime composition while stable references survive a Home Assistant entity
rename and no non-activation operation changes control.
