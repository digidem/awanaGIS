# GISBR Vendor Attribution & Patch Record

AwanaGIS bundles a pinned, isolated runtime subset of **GISBR** so users do not need to install a second QGIS plugin.

## Upstream Source

- **Repository:** <https://github.com/d-camargo/gisbr.git>
- **Pinned Commit SHA:** `06d84dfab9942e4e840637bb8d8f96af173330ad`
- **License:** GNU General Public License v3.0 (see [`vendor/gisbr/LICENSE`](./vendor/gisbr/LICENSE))
- **Combined Work Notice:** AwanaGIS derives from AgenticGIS (GPL-2.0-or-later) and includes adapted GISBR runtime modules (GPL-3.0); the combined distribution is conveyed in compliance with **GPL-3.0**.

## Vendored Runtime Scope

Copied under `integrations/brazil/vendor/gisbr/`:
- `provider.py`, `plugin_icon.py`, `icon.png`, `icon.svg`
- `core/` (source registry `sources.py`, diagnostic engine `diagnostico.py`, geographic scopes `recorte.py`, connectors `wfs.py`, `arcgis_rest.py`, `zip_remoto.py`, `cog_raster.py`, `ibge_agregados.py`, `local_file.py`, `osm.py`, `basemap.py`, `github_release.py`, SSL CA support `ssl_support.py` & `certs/`, bundled IBGE/DATASUS/MapBiomas/geobr CSVs in `data/`, geobr v1/v2 loaders, OSM/rede/agro/censo pipelines)
- `algorithms/` (all 57 `read_*`, `join_censo`, `export_poi_gmns`, `osm_network` Processing algorithms)
- `LICENSE` (verbatim GPL-3.0 license text from upstream GISBR)

Excluded from runtime bundle:
- `geobr_qgis_plugin.py` (standalone plugin entry point)
- `gui/diagnostico_dock.py` (duplicate GISBR dock UI)
- `metadata.txt`, `tests/`, `docs/`, `tools/`

## Documented Patches Applied to Vendored Copy

1. **Package-scoped `__init__.py`:** Replaced standalone QGIS `classFactory` entry point with a minimal package docstring so QGIS never loads the vendored copy as a duplicate plugin.
2. **Processing provider namespacing (`vendor/gisbr/provider.py`):**
   - Changed `GeobrProvider.id()` from `"gisbr"` to `"awanagis_brazil"`.
   - Changed `GeobrProvider.name()` from `"GISBR"` to `"AwanaGIS Brazil"`.
   - Updated `GeobrProvider.longName()` to `"AwanaGIS Brazil — Brazilian spatial data (derived from GISBR, IBGE/IPEA)"`.
3. **Eliminated absolute `gisbr.*` imports (`vendor/gisbr/core/recorte.py`):**
   - Rewrote `from gisbr.core.constants import UF_CODE_TO_ABBREV` to relative `from .constants import UF_CODE_TO_ABBREV`. No `sys.path` or `sys.modules` mutation is performed.
4. **Updated internal Processing algorithm IDs (`gisbr:<alg>` -> `awanagis_brazil:<alg>`):**
   - `vendor/gisbr/core/recorte.py`
   - `vendor/gisbr/core/diagnostico.py`
   - `vendor/gisbr/core/osm_pipeline.py`
   - `vendor/gisbr/core/censo_join.py` (docstring)
   - `vendor/gisbr/core/osm_topologia.py` (comment)
   - `vendor/gisbr/algorithms/diagnostico/export_poi_gmns.py` (docstring)
   - `vendor/gisbr/algorithms/diagnostico/osm_network.py` (docstring/comment)
5. **Plugin lifecycle registration (`integrations/brazil/runtime.py` & `plugin.py`):**
   - Provider is registered exclusively in `AwanaGisPlugin.initGui()` and unregistered exclusively in `AwanaGisPlugin.unload()` via instance tracking, leaving any separately installed `gisbr` plugin untouched.

## Refreshing the Pinned Snapshot

To refresh from a newer reviewed GISBR commit:
1. Clone `https://github.com/d-camargo/gisbr.git` into a temporary directory outside the repository and check out the audited commit SHA.
2. Re-sync `core/`, `algorithms/`, `provider.py`, `plugin_icon.py`, `icon.*`, and `LICENSE` into `integrations/brazil/vendor/gisbr/`.
3. Re-apply the relative-import and `awanagis_brazil` provider namespace patches above.
4. Update the pinned SHA and patch inventory in this file and run the full `tests/test_brazil_*.py` suite.
