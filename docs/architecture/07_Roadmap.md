# Roadmap

Milestone 26 uses published immutable core `0.2.0` and released integration
`0.4.0` with
asymmetric hysteresis, command-dispatch-based minimum on/off protection,
deferred deadline reevaluation, and operational diagnostics. Persistence of
hysteresis/source-control history is explicitly deferred; restart begins with
unknown dispatch history and no fabricated lockout.

Milestone 26.1 prepares integration `0.5.0` with Basic, Detailed, and Debug
diagnostic profiles; stable timing entities; a translated operational summary;
allowlisted observability diagnostics; and one lifecycle-owned active-countdown
refresh scheduler. It does not change core decisions or claim physical
heat-source feedback.

## Milestone 23: Home Assistant one-zone host vertical slice

The first host integration proves:

```text
configured HA temperature entity
-> Measurement
-> dedicated serialized ControlRuntime worker
-> HeatSourceCommand
-> configured blocking HA service call
```

Scope is one config entry, one zone, one primary sensor, and one shared heat
source. It includes config flow, lifecycle, initial-state buffering, a
one-shot Home Assistant scheduler, typed runtime data, and Repairs issues for
operational failures.

Deferred work included multi-zone configuration UI, options/reconfigure flows,
persistence, discovery, polling, diagnostic entities, HACS packaging, physical
confirmation, generic service data, retries, hardware protocols, modulation,
DHW, valves, learning, and frontend panels.

Before normal HACS distribution, the reusable core must be released as a
versioned package and referenced by a pinned custom-component requirement.

## Milestone 24B: controlled core release

Milestone 24B1 prepared the `controlel` core distribution with explicit PEP 517
metadata, wheel and sdist content validation, clean out-of-checkout wheel
installation, and non-publishing packaging CI.

Milestone 24B2 published immutable core `controlel==0.1.0` and independently
verified its public files. Integration `0.1.1` pins that exact dependency and
CI validates both local editable compatibility and an isolated public package
composition. Core and integration versions now evolve independently.

At the conclusion of Milestone 24B, HACS metadata, brands metadata,
integration tagging, GitHub release packaging, and end-user HACS distribution
remained later release work.

## Milestone 24C: controlled Home Assistant distribution

Milestone 24C1 adds HACS metadata, a deterministic allowlisted integration ZIP,
independent archive validation, non-publishing CI, removal cleanup, and
end-user documentation. It does not create a tag or release.

Milestone 24C2 is the separately approved integration tag, GitHub Release, and
clean custom-HACS installation validation. The repository-wide release stream
is reserved for integration releases; core provenance may use tags but not
GitHub Releases in this monorepo.

Milestone 24C3 remains optional Home Assistant Brands work and submission to
the HACS default repository after the custom-repository release is stable.

## Milestone 25A: editable configuration UX

Milestone 25A prepares integration `0.2.0` while retaining core
`controlel==0.1.0`. It adds generated stable IDs, filtered temperature
selection, safe defaults, a simple controlled-switch mode, lossless advanced
service bindings, and a two-step Options Flow. Existing `0.1.1` entries load
without migration: mutable options override legacy data, while IDs remain
stable in entry data. Every successful update fully unloads and reconstructs
one runtime.

## Milestone 25B: operational visibility

Milestone 25B prepares integration `0.3.0` with one immutable integration-side
operational snapshot, one zone-controller device, read-only operational and
diagnostic entities, explicit measurement/demand/safety/command states, and
allowlisted config-entry diagnostics. A bounded 20-record decision trace and
all snapshot state are in memory only. Entity unique IDs use the config entry
ID, so display-name changes and reloads do not duplicate entities. This
milestone does not change core `0.1.0` heating behavior and does not claim
physical output confirmation.

Milestone 25B.1 prepares the focused `0.3.1` integration patch with
configuration provenance, exact seconds/minutes Options Flow round trips,
allowlisted configuration-change logging, clearer entity presentation, and
truthful grace countdown and deadline visibility. Core behavior remains
unchanged at `0.1.0`.

Milestone 26 and later retain multiple zones or sensors, persistence,
climate/number/select entities, physical output feedback, automatic retry,
heating curves, modulation, DHW, learning, and dashboard work. Versions `0.3.0`
and `0.3.1` are the published integration line preceding Milestone 26.
