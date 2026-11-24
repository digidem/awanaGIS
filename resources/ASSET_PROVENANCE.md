# AwanaGIS Asset Provenance (`resources/ASSET_PROVENANCE.md`)

## Approved Product Icon (`resources/icon.svg`, `resources/icon.png`)

- **Status:** **APPROVED — derived from the official Awana Digital mark supplied by the maintainer.**
- **Authoring & derivation:**
  - Source mark: `551x547` RGBA PNG official Awana Digital mark provided by the project maintainer.
  - Raster asset (`resources/icon.png`): Aspect-preserved center fit (`124x123` with 2px transparent padding) on a `128x128` RGBA canvas using Lanczos resampling, palette-quantized via `pngquant` (`--quality=85-98`) and losslessly optimized via `oxipng -o 4 --strip safe` (`9,676` bytes).
  - Vector-wrapper asset (`resources/icon.svg`): `128x128` SVG wrapping the compressed official `icon.png` so Qt SVG consumers (`QSvgRenderer`) and PNG consumers (`QIcon`) render the identical mark.
- **Legibility targets:** Verified by offscreen raster rendering at `16x16`, `24x24`, `32x32`, `64x64`, and `128x128` px.
- **License:** Distributed with AwanaGIS under `GPL-2.0-or-later`.

## Third-Party CLI Identification Marks (`gui/agent_logos.py`)

- Inline SVG marks in `gui/agent_logos.py` identify external third-party CLI tools (Claude Code, Codex, Cursor, Gemini, OpenCode, etc.) in the Settings CLI Agent picker.
- They are inherited from upstream `AgenticGIS` (`1e4f70b`) for nominative identification of each user-installed CLI and remain the trademarks of their respective owners.

## Typography

- No proprietary or external font binaries (`.ttf`/`.otf`/`.woff2`) are bundled in `resources/` or the plugin ZIP.
- `gui/brand.py` and `gui/theme.py` reference Awana Digital's font roles (`Tomorrow` display, `Public Sans` body, `Space Grotesk` caption) when installed on the system, with automatic fallback to the native QGIS/Qt UI sans-serif font.
