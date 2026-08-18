Project data workflow for the Remotion POC

- Authoritative source: video/projects/*.yaml (human-authored)
- Generated/browser-safe data: video/src/generated/projects.json (derived)

Why
- Remotion compositions are browser-bundled and must not import Node core modules (fs, path).
- This repository keeps YAML as the single source of truth and compiles it to browser-safe JSON before bundling.

How it works
- A Node-only preparation script reads video/projects/*.yaml, validates minimal shape, and writes deterministic JSON to video/src/generated/projects.json.
  - Script: node scripts/prepare-projects.mjs
- npm scripts run the prepare step automatically before typecheck, studio, and render.

Commands (run from video/ directory)
- npm run prepare       # generate video/src/generated/projects.json from YAML
- npm run typecheck     # runs prepare then tsc --noEmit
- npm run studio        # runs prepare then starts remotion studio
- npm run render        # runs prepare then renders to output/CTL-EDU-001.mp4

Generated files
- video/src/generated/projects.json is derived output and recreated by npm run prepare.
- For this POC the generated file is not treated as first-class source; the YAML files in video/projects are authoritative.

Notes
- Do not import Node-only modules from code that will be browser-bundled (e.g. project-loader used by Remotion). Use the generated JSON instead.
- Public assets remain under video/public/ and should be referenced via Remotion's staticFile() at runtime.
