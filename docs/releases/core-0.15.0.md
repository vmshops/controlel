# Controlel Core 0.15.0

Status: published on PyPI. Publication rechecked during 0.18.0 closure.
No public `core-v0.15.0` tag was found; source-to-artifact provenance is unverified.
The feature description below is the historical candidate description.

This Core boundary carries the Setup recommendation fixes required by the
Home Assistant setup wizard:

- candidate identity no longer expires solely because discovery was captured
  at a later timestamp;
- Controlel-owned entities are not offered as Heating inputs;
- temperature candidates require advertised temperature capability;
- heat-source candidates are restricted to meaningful control domains; and
- a preferred area ranks before other areas, followed by capability confidence
  and identity quality.

There is no runtime algorithm, activation, canonical schema, migration, or
automatic migration change in the historical candidate description. Published Core 0.14.0 artifacts,
tags, hashes, and release records remain immutable.
