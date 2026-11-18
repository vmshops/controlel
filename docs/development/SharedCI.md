# Shared Woodpecker CI candidate

This candidate onboards `vmshops/controlel` to the existing shared Woodpecker
server. It does not deploy the integration or contact physical Home Assistant,
heating, boiler, valve or production devices. All five existing GitHub Actions
files remain unchanged and active until the coordinator has actual evidence
for this repository on the exact candidate commit.

## Task contract and evidence

CONTROL assigned this bounded CI/docs task to the existing Codex worker,
without changing its model or reasoning configuration. The immutable baseline
is `26c3bc5a44ee59485c04cff2bcf3208239e3fa70`. WRITE branch:
`task/ci02-onboarding`; isolated worktree: `work/projects/controlel` under the
CI-02 workspace, backed by its own `work/project-repos/controlel.git` bare clone.
No user's checkout, product code, dependency lock, release state or device is
changed. No push, merge, GitHub/CI mutation or deployment belongs to this worker.

Before editing, repository `scripts/agent/preflight.ps1` checked the explicit
anchor, baseline, worktree, branch, WRITE mode, `fast` profile and task Python
3.14 interpreter, and finished with `=== PREFLIGHT OK ===`. The same preflight
must precede verification with the exact committed candidate as `ExpectedHead`.
Acceptance requires a coordinator review and actual Woodpecker runs; local
syntax/provenance checks are not a successful Core/HA pilot.

As of 2026-11-18, the coordinator reports GitHub
`GET /repos/vmshops/controlel/hooks` returning 404 during OAuth activation.
Organization app access is not available. Activation/webhook setup and all live
Woodpecker workflows are **BLOCKED / NOT RUN**; no FULL result is claimed.

Local preparation verification: **PASS** for three Linux-only provenance/guard
tests (`python3 -B scripts/ci/test_harness.py -v`), three existing development
harness architecture contracts, Bash parsing of all seven runner/CI shell
scripts, parsing all five workflow YAML files, Ruff lint/format of the added
test script and Git whitespace validation. Disposable Linux Git checkouts and
environments exercise wrong SHA/event/profile, missing/changed lock,
foreign-worktree fingerprints and refusal to overwrite provenance. These are
runner tests, not HA framework execution. Runner image build, dependency
installation, Core, HA adapter/framework, packaging and official hassfest are
**NOT RUN** by this preparation worker. HACS remains on GitHub as below.

## Exact coverage mapping

| Existing Actions source | Woodpecker workflow | Commands preserved |
|---|---|---|
| `tests.yml` / `core-and-adapters` | `core` | Editable Core install, existing packaging tools, Ruff lint + format, complete domain/application/frontend_api/infrastructure/architecture/packaging test directories. |
| `tests.yml` / both checked-out-wheel HA jobs | `ha-checked-out` | Hash-locked HA dependencies; wheel built from selected checkout; `verify_public_core.py --development-wheel`; adapter and framework suites as separate pytest runs. |
| `home-assistant-published-core.yml`, called by `integration-release-validation.yml` | `ha-public` | Exact manifest `controlel==0.18.0` from PyPI through `public_core_artifact.py --install`; original artifact size/SHA/installed-byte and public API checks; public adapter and framework suites. No source/wheel fallback. |
| `packaging.yml` | `packaging` | `build_core_release.py`, `twine check`, `validate_artifacts.py`, `verify_clean_install.py`. |
| `integration-release-validation.yml` / release-artifact | `integration-release` after `ha-public` | Existing HACS archive build/validation for approved integration version `0.14.2`, including original checksum validation. |
| `hassfest.yml` and integration release hassfest job | `integration-release` / `hassfest` | Official hassfest container runs its real `script.hassfest --action validate` CLI against this checkout's integration. |
| Integration release HACS action | **Still GitHub Actions only** | Official HACS repository/API validation is not reproduced or replaced by local archive checks. |

FAST runs the complete applicable suites above, filtered by changed paths.
Pushes on `main`/`develop` and pull requests trigger those filters. Documentation
alone does not require these suites. Manual FULL and RELEASE bypass path filters
and run all five workflows. `manual` defaults to FULL; tag/release defaults to
RELEASE; push/PR defaults to FAST. Explicit `TEST_PROFILE` accepts only those
three values. Each Python wrapper requires Linux, Python **3.14.x >= 3.14.2**,
and checkout HEAD equal to the full 40-hex `CI_COMMIT_SHA` before installing or
running anything. The initial integration-release step guards the checkout
before its following hassfest container uses that same workspace.

FULL and RELEASE currently run the same test/check coverage. RELEASE does not
publish, tag, install on HA, or deploy. It builds inspection files in the
ephemeral workflow workspace. Durable seven-day inspection-artifact upload
remains in the unchanged GitHub workflow; no Transport upload token, artifact
directory or other project's credentials are reused here. The existing weekly
GitHub schedule remains there as well. A green Woodpecker result covers only
the mapped checks, not the still-unported HACS action or device validation.

## Runtime and isolation requirements

An administrator must build `infra/ci/Dockerfile` on the CI host and tag it
`vmshop-ci/controlel-python:ci02-20261117`. Workflows use `pull: false`; a missing
runner must fail instead of pulling another image. The base is official
`python:3.14-bookworm`; the Dockerfile and scripts both reject older/different
minor versions. System packages: Git, CA certificates, compiler/build tools,
pkg-config, ffmpeg, libffi/OpenSSL/JPEG/zlib development files, libudev,
libpcap and libturbojpeg. This provides a Linux glibc runtime suitable for the
existing Python3.14 HA lock; actual dependency installation remains a live
acceptance check, including any unavailable wheel/source-build requirements.

Each Core/HA/packaging step creates a fresh task-scoped temporary venv and
removes it on exit. No editable install is shared between Core and either HA
composition. HA uses the unchanged `requirements/ha-test.txt` with
`--require-hashes`. Existing `requirements/package-test.txt` pins are preserved;
its transitive dependencies and the existing Core Actions' Ruff/pytest/Core
dependency installation are not a complete hash lock. No stronger lock claim
is made and no lock is regenerated by CI.

The canonical `scripts/agent/ha-test.sh` remains the HA execution entry point.
Its preparer/fingerprint still bind baseline ancestry, exact worktree, profile
and HA lock SHA-256. Windows-created worktree metadata still uses `git.exe`
through WSL; native Linux clones use native Git. The added explicit `public`
profile verifies the original published Core contract before each pytest run.

The hassfest step uses `ghcr.io/home-assistant/hassfest:latest`, matching the
image selected by the existing pinned upstream action. The action revision
does not pin that image's contents. The administrator can record/pin the
resolved image digest after testing it; neither a local substitute nor a
successful archive check is accepted as hassfest evidence.
The CLI comes from the official image at `/usr/src/homeassistant`; it receives
the integration path under Woodpecker's `CI_WORKSPACE` and needs no Docker
CLI/socket or extra mounts. See the existing action's
[definition](https://github.com/home-assistant/actions/blob/e3fb68ebda13d88a0d695082f471ba2c83d025fb/hassfest/action.yml)
and upstream [container entrypoint](https://github.com/home-assistant/core/blob/dev/script/hassfest/docker/entrypoint.sh).

Repository trust for security/network/volumes must stay disabled. No step is
privileged; none mounts the host Docker socket, devices, production paths or
credentials. External fork revisions require review before approval/manual
runs. These checks require no project secrets. Allow outbound HTTPS/DNS to
PyPI, `files.pythonhosted.org`, required public GitHub metadata and image
registries; block other private/production network access. Plan for sizeable
HA dependency downloads, temporary virtualenvs and two HA compositions. Start
with one pipeline and conservative concurrency, then measure actual RAM/disk
and duration; no measured resource claim is available yet.

## Explicit remaining HACS scope

The existing pinned [HACS action](https://github.com/hacs/action/blob/1ebf01c408f29afcb6406bd431bc98fd8cbb15aa/action.yml)
runs `ghcr.io/hacs/action:main` and accepts the GitHub-generated token/context.
Its remote repository validation differs from deterministic archive validation.
No equivalent GitHub API identity/context has been provisioned for Woodpecker,
and this task does not create one or send comments. Keep the existing HACS job
active. Before any Actions retirement, the coordinator must either run the
actual official validator with a reviewed repository-scoped read credential,
correct repository/ref/event context and comments disabled, or explicitly keep
that check on GitHub. Do not label complete replacement until it has proof.

## Coordinator acceptance

1. Obtain organization OAuth access and activate the exact repository/webhook.
2. Build the runner and resolve the official hassfest image; keep repository
   trust flags disabled and fork approval enabled.
3. Review the candidate diff. The first commit carries `[skip actions]` to
   avoid billed Actions for onboarding; do not use `[skip ci]`, which also
   suppresses Woodpecker.
4. Run manual FULL on the exact candidate SHA and inspect all five workflow
   statuses, complete logs and both HA compositions. Repeat RELEASE for its
   actual selected SHA if it will be used as a release gate.
5. Record remaining HACS/artifact/schedule coverage explicitly. Only after live
   proof may CONTROL decide whether/how to change the retained Actions.
