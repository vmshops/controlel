branding/ README

Purpose
-------
This folder contains master brand assets and guidance. Vector/source artwork
should be stored here as the canonical source. Derived assets for specific
consumers (GitHub, docs, social) should not be committed to this folder but
produced by a release/branding process and placed in .github/assets/ or
docs/assets/ instead.

Conventions
-----------
- branding/logo-horizontal.svg   -- master horizontal logo (vector)
- branding/logo-icon.svg         -- master square/icon logo (vector)
- branding/README.md             -- brand usage rules, colors, alt text
- .github/assets/                -- GitHub social preview, release banners
- docs/assets/                   -- documentation screenshots and diagrams

Guidelines
----------
- Keep master vectors in SVG or source tool native formats. Do not commit
  proprietary font files without explicit license review.
- Provide light and dark theme variants where needed; name them explicitly,
  e.g. logo-horizontal-light.svg and logo-horizontal-dark.svg.
- Include short alt text for each image in docs or README references.
- Do not duplicate master artwork across multiple folders; reference the
  canonical source in branding/ and keep consumer folders for derived raster
  exports only.
