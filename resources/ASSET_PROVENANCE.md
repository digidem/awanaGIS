# AwanaGIS Asset Provenance (`resources/ASSET_PROVENANCE.md`)

## Draft Product Icon (`resources/icon.svg`, `resources/icon.png`)

- **Status:** **DRAFT PROPOSAL — awaiting Awana Digital design-team signoff.**
- **Do not treat as an approved final Awana Digital or AwanaGIS logo.**
- **Authoring & derivation:** Newly authored vector geometry (stacked geospatial map planes and waypoint mark) created specifically for the AwanaGIS plugin, using only the official Awana Digital palette extracted in [`docs/branding/brand-tokens.json`](../docs/branding/brand-tokens.json):
  - AD Dark Burgundy (`#6B0030`)
  - AD Burgundy (`#8D003E`)
  - AD Cream (`#FDF7EF`)
  - AD Pollen (`#FFE460`)
- **Parent-brand separation:** Does **not** copy, stretch, recolor, or mutate Awana Digital's parent rectangle, circle, square, or wordmark logos referenced in [`docs/branding/brand-guide.md`](../docs/branding/brand-guide.md).
- **Legibility targets:** Verified by offscreen raster rendering at `16x16`, `24x24`, `32x32`, `64x64`, and `128x128` px.
- **License:** Distributed with AwanaGIS under `GPL-2.0-or-later`.

## Third-Party CLI Identification Marks (`gui/agent_logos.py`)

- Inline SVG marks in `gui/agent_logos.py` identify external third-party CLI tools (Claude Code, Codex, Cursor, Gemini, OpenCode, etc.) in the Settings CLI Agent picker.
- They are inherited from upstream `AgenticGIS` (`1e4f70b`) for nominative identification of each user-installed CLI and remain the trademarks of their respective owners.

## Typography

- No proprietary or external font binaries (`.ttf`/`.otf`/`.woff2`) are bundled in `resources/` or the plugin ZIP.
- `gui/brand.py` and `gui/theme.py` reference Awana Digital's font roles (`Tomorrow` display, `Public Sans` body, `Space Grotesk` caption) when installed on the system, with automatic fallback to the native QGIS/Qt UI sans-serif font.
