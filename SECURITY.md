# Security policy

## Supported versions

No Home Assistant integration release has been published. When releases begin,
only the latest integration patch and its exact declared core dependency will
receive security fixes. Published tags and release assets are immutable;
corrections use a higher version.

## Reporting

Report ordinary defects through
<https://github.com/vmshops/controlel/issues>. Do not place credentials,
private keys, access tokens, private Home Assistant configuration, or
vulnerability exploit details in a public issue. For a sensitive report,
contact the repository owner privately through GitHub before disclosure.

Include the integration version, Home Assistant version, relevant sanitized
logs, and whether installation used HACS or the manual release archive.

## Release integrity

Official integration releases use the tag `vX.Y.Z`, a fixed
`controlel.zip` asset, and a `controlel.zip.sha256` checksum. Verify the
checksum before manual installation. The integration requires an exact
published `controlel` core version from PyPI and never bundles core source,
credentials, tests, or development files in its release archive.
