# Controlel Home Assistant integration 0.11.0

Status: published

Summary
-------
Home Assistant integration version 0.11.0 is published as the integration
package. By design this integration depends on the public Core 0.10.0 release
and its manifest pins `controlel==0.10.0`.

Compatibility and installation
------------------------------
- Integration version: 0.11.0
- Required Core package: controlel==0.10.0 (pinned in custom_components/controlel/manifest.json)
- Config-entry version: 1

Tagging provenance
------------------
- Git tag: v0.11.0
- Tag object timestamp (tagged_at): recorded in release-metadata/releases.yaml


Release model
-------------
- HA integration releases use GitHub Releases and include a single canonical
  controlel.zip artifact and checksums. The GitHub Release body is produced
  from repository release metadata and release-note fragments. The uploaded
  artifact is the approved canonical HA package.

Notes
-----
- The HA integration may be updated independently of Core; the integration's
  release cadence and Core release cadence are intentionally decoupled.
- For technical details about installation and HACS, see the developer docs
  at `docs/operations/HomeAssistantInstallation.md`.
