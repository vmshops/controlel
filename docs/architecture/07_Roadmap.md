# Roadmap

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

Deferred work includes multi-zone configuration UI, options/reconfigure flows,
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

HACS metadata, brands metadata, integration tagging, GitHub release packaging,
and end-user HACS distribution remain later release work.
