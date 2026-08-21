"""Lightweight release-metadata validator (schema v1 checks).

Usage: python scripts/validate_release_metadata.py release-metadata/releases.yaml

This script performs non-network checks: YAML syntax, required top-level keys,
unique component+version pairs, and simple published-release field presence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate(releases_yaml: dict) -> int:
    if not isinstance(releases_yaml, dict):
        print("Top-level structure must be a mapping", file=sys.stderr)
        return 2
    if releases_yaml.get("metadata_version") != 1:
        print("metadata_version must be 1", file=sys.stderr)
        return 2
    releases = releases_yaml.get("releases")
    if not isinstance(releases, list):
        print("releases must be a list", file=sys.stderr)
        return 2
    seen = set()
    for r in releases:
        if not isinstance(r, dict):
            print("each release entry must be a mapping", file=sys.stderr)
            return 2
        comp = r.get("component")
        ver = r.get("version")
        if not comp or not ver:
            print("release entry missing component/version", r, file=sys.stderr)
            return 2
        key = (comp, ver)
        if key in seen:
            print("duplicate component+version found", comp, ver, file=sys.stderr)
            return 2
        seen.add(key)
        if r.get("status") == "published":
            if r.get("version") is None:
                print("published release missing version", r, file=sys.stderr)
                return 2
            # if tag present, ensure it's non-empty and the tag object timestamp is recorded
            if r.get("tag") is not None and not isinstance(r.get("tag"), str):
                print("tag must be string or null", r, file=sys.stderr)
                return 2
            if r.get("tag") is not None:
                # for tag-bound published releases require 'tagged_at' (tag object tagger timestamp)
                tagged_at = r.get("tagged_at")
                if tagged_at is None or not isinstance(tagged_at, str):
                    print("tag-bound published release missing tagged_at (tag object timestamp)", r, file=sys.stderr)
                    return 2
    # Additional local consistency checks for Home Assistant integration
    # Verify that published HA release points to the pinned core required by manifest
    repo_root = Path(__file__).resolve().parents[1]
    manifest_path = repo_root / "custom_components" / "controlel" / "manifest.json"
    const_path = repo_root / "custom_components" / "controlel" / "const.py"
    try:
        import json

        if manifest_path.exists():
            with manifest_path.open("r", encoding="utf-8") as mf:
                manifest = json.load(mf)
        else:
            manifest = None
    except Exception as e:
        print("failed to read manifest.json:", e, file=sys.stderr)
        return 2

    # Validate the release entry matching the checked-out manifest. Historical
    # published entries remain immutable and need not match a newer candidate.
    manifest_version = manifest.get("version") if manifest else None
    matching_ha_releases = [
        release
        for release in releases
        if release.get("component") == "home_assistant" and release.get("version") == manifest_version
    ]
    if manifest and len(matching_ha_releases) != 1:
        print("release metadata must contain exactly one HA entry matching manifest version", file=sys.stderr)
        return 2
    for r in matching_ha_releases:
        if r.get("status") in {"candidate", "pretag", "published"}:
            comp = r.get("compatibility", {})
            required_core = comp.get("required_core") or comp.get("ha_manifest_pinned_core")
            if manifest:
                reqs = manifest.get("requirements", [])
                pinned = None
                if reqs:
                    # look for first controlel==X requirement
                    for req in reqs:
                        if req.startswith("controlel=="):
                            pinned = req.split("==", 1)[1]
                            break
                if pinned is None:
                    print("manifest does not pin controlel version", file=sys.stderr)
                    return 2
                if required_core is None:
                    print("release metadata missing compatibility.required_core for HA", file=sys.stderr)
                    return 2
                if pinned != required_core:
                    msg = f"HA required_core mismatch: releases.yaml says {required_core}, manifest pins {pinned}"
                    print(msg, file=sys.stderr)
                    return 2
            # verify config entry version matches const
            if const_path.exists():
                try:
                    const_text = const_path.read_text(encoding="utf-8")
                    import re

                    m = re.search(r"CONFIG_ENTRY_VERSION\s*=\s*(\d+)", const_text)
                    if m:
                        const_version = int(m.group(1))
                        meta_config_entry = r.get("compatibility", {}).get("config_entry_version")
                        if meta_config_entry is None:
                            print("release metadata missing compatibility.config_entry_version for HA", file=sys.stderr)
                            return 2
                        if int(meta_config_entry) != const_version:
                            msg = (
                                "HA config_entry_version mismatch: releases.yaml "
                                f"{meta_config_entry} != const.py {const_version}"
                            )
                            print(msg, file=sys.stderr)
                            return 2
                    else:
                        print("could not find CONFIG_ENTRY_VERSION in const.py", file=sys.stderr)
                        return 2
                except Exception as e:
                    print("failed reading const.py:", e, file=sys.stderr)
                    return 2
    print("release-metadata validation: ok")
    return 0


def main(argv):
    if len(argv) < 2:
        print("Usage: validate_release_metadata.py <releases.yaml>")
        return 2
    path = Path(argv[1])
    if not path.exists():
        print("file not found", path, file=sys.stderr)
        return 2
    data = load_yaml(path)
    return validate(data)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
