# Third-Party Licenses & Asset Notices

## 1. Combined Distribution License
Because AwanaGIS bundles adapted **GPL-3.0** modules from GISBR alongside **GPL-2.0-or-later** code derived from AgenticGIS and **MIT** code from CoMapeo Map Builder (`qgis-smp-plugin`), the combined AwanaGIS distribution is conveyed under **GPL-3.0-or-later** (see [`LICENSE`](LICENSE) and [`LICENSES/`](LICENSES/)). All original copyright and license notices remain intact.

## 2. Upstream Codebases

### AgenticGIS (Base Plugin Architecture)
- **Source:** https://github.com/ultramenid/AgenticGIS
- **Baseline SHA:** `1e4f70b488824982a835c89c202454ec92dafae7` (`v0.4.6`), plus Brazilian Portuguese localization commits (`f0c552a`, `51c8a79`)
- **Copyright:** `Copyright (C) 2026 Muhammad Alichamdan <malichamdan@gmail.com>`
- **License:** `GPL-2.0-or-later` (see [`LICENSES/GPL-2.0.txt`](LICENSES/GPL-2.0.txt))

### GISBR (Brazilian Public Spatial Data & Processing Algorithms)
- **Source:** https://github.com/d-camargo/gisbr
- **Pinned SHA:** `06d84dfab9942e4e840637bb8d8f96af173330ad`
- **Vendored path:** `integrations/brazil/vendor/gisbr/` (plus `integrations/brazil/VENDOR_ATTRIBUTION.md`)
- **License:** `GPL-3.0` (see [`LICENSES/GPL-3.0.txt`](LICENSES/GPL-3.0.txt))
- **Adaptations:** Rewrote absolute `gisbr.*` imports to relative imports, removed `sys.path` mutation, namespaced Processing provider ID to `awanagis_brazil` to avoid collisions with standalone `gisbr`, and registered provider lifecycle strictly in `AwanaGisPlugin.initGui()`/`unload()`.

### CoMapeo Map Builder (`qgis-smp-plugin` — `.smp` Raster Tile Renderer)
- **Source:** https://github.com/digidem/qgis-smp-plugin
- **Pinned SHA:** `34715788e94718d036a58f9992d7ef69b9ecf3d5` (`v0.9.0`)
- **Vendored path:** `integrations/smp/vendor/` (plus `integrations/smp/VENDOR_ATTRIBUTION.md`)
- **Copyright:** `Awana Digital / Digital Democracy`
- **License:** `MIT` (see [`LICENSES/MIT-comapeo-smp.txt`](LICENSES/MIT-comapeo-smp.txt))
- **Adaptations:** Isolated `SMPGenerator` to accept an explicit main-thread project snapshot (`project=`) rather than calling `QgsProject.instance()` on background threads, and treated `QgsMapRendererCustomPainterJob.errors()` as tile render failures.

## 3. Third-Party CLI Brand Marks (`gui/agent_logos.py`)
- Inline SVG marks in `gui/agent_logos.py` are inherited from upstream AgenticGIS to help users visually identify external CLI agents installed on their system.
- All third-party product names and brand marks remain the trademarks and property of their respective owners and are used strictly for nominative identification.

## 4. Brand Typography
- Official Awana Digital brand font roles (`Tomorrow`, `Public Sans`, `Space Grotesk`) are referenced by family name in `gui/brand.py` and `gui/theme.py` when present on the host OS.
- **No external font binaries are bundled** in this repository or plugin ZIP; the UI falls back cleanly to the native QGIS / Qt system sans-serif font.

## 5. Product Icon (`resources/icon.svg`, `resources/icon.png`)
- Derived from the official Awana Digital mark supplied by the maintainer, resized to `128x128` and compressed with `pngquant` + `oxipng` (`9,676` bytes). See [`resources/ASSET_PROVENANCE.md`](resources/ASSET_PROVENANCE.md).
