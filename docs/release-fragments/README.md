Release fragment conventions

Purpose
-------
Release fragments are short, focused markdown files created by contributors to
summarize a user-visible change that should be included in the next release
notes. Fragments are intentionally small and reviewable; they are not a
replacement for a PR description, but provide structured input for automated
release-note composition.

Location
--------
Place fragments in `docs/release-fragments/` with a filename that references the
PR or a short identifier, e.g. `PR-1234-feature-reporting.md`.

Minimal fragment template
-------------------------
```
---
component: core            # core | home_assistant | docs | website | other
type: feature              # feature | fix | safety | compatibility | docs | internal
summary: "Short one-line summary suitable for release notes"
---
A brief human paragraph with context, why this change matters, and a short example
or link to relevant docs/PR.
```

Guidelines
----------
- Keep fragments concise (one short paragraph + metadata).
- Prefer adding a fragment only for user-facing changes (features, fixes,
  compatibility notes, or safety/security). Internal refactors do not require
  fragments unless they change user behavior.
- During release preparation, automation will collect fragments, group them by
  type, and render release notes. After inclusion, fragments may be moved to an
  archive folder under `docs/releases/archive/<version>/`.

