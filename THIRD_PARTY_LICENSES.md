# Third-Party Licenses & Asset Notices

## 1. Upstream Codebase: AgenticGIS
- **Source:** https://github.com/ultramenid/AgenticGIS
- **Baseline SHA:** `1e4f70b488824982a835c89c202454ec92dafae7` (`v0.4.6`), plus Brazilian Portuguese localization commits (`f0c552a`, `51c8a79`)
- **Copyright:** `Copyright (C) 2026 Muhammad Alichamdan <malichamdan@gmail.com>`
- **License:** `GPL-2.0-or-later` (see [`LICENSE`](LICENSE))

## 2. Python Runtime Dependencies
- **None bundled.** AwanaGIS runs solely on Python's standard library and the host QGIS / PyQt environment.

## 3. Third-Party CLI Brand Marks (`gui/agent_logos.py`)
- Inline SVG marks in `gui/agent_logos.py` are inherited from upstream AgenticGIS to help users visually identify external CLI agents installed on their system (e.g., Claude Code, Codex CLI, Cursor, Gemini CLI, OpenCode, GitHub Copilot, etc.).
- All third-party product names and brand marks remain the trademarks and property of their respective owners and are used strictly for nominative identification.

## 4. Brand Typography
- Official Awana Digital brand font roles (`Tomorrow`, `Public Sans`, `Space Grotesk`) are referenced by family name in `gui/brand.py` and `gui/theme.py` when present on the host OS.
- **No external font binaries are bundled** in this repository or plugin ZIP; the UI falls back cleanly to the native QGIS / Qt system sans-serif font.

## 5. Draft Product Icon (`resources/icon.svg`, `resources/icon.png`)
- Newly authored draft AwanaGIS icon in Awana Digital's official palette (`#6B0030`, `#8D003E`, `#FDF7EF`, `#FFE460`), awaiting Awana Digital design-team signoff. See [`resources/ASSET_PROVENANCE.md`](resources/ASSET_PROVENANCE.md).

## 6. Planned Future Integrations (Not Bundled Here)
- **GISBR** (`https://github.com/d-camargo/gisbr`, `GPL-3.0`): Not present in this branding-only baseline.
- **CoMapeo SMP Plugin** (`https://github.com/digidem/qgis-smp-plugin`, `MIT`, Awana Digital): Not present in this branding-only baseline.
