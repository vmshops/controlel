# Architecture

The maintained architecture description is
[architecture/02_Architecture.md](architecture/02_Architecture.md). Repository
changes must also follow the boundary and truthfulness rules in the repository
root AGENTS.md (see the file at the repository root).

UI and configuration layer separation (Observability UI vs HA Configure vs
future Configuration UI and Wizard) is documented in
[architecture/UILayers.md](architecture/UILayers.md).

The allowed internal dependency direction is:

```text
domain
  <- application
       <- Home Assistant adapter / infrastructure
```

Domain code contains models and business rules. Application code orchestrates
those rules and defines host-facing ports. Home Assistant and infrastructure
adapt external systems to those ports. Command, observation, assessment,
diagnostic projection, and presentation remain separate concepts.
