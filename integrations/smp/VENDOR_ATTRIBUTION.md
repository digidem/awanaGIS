# Vendor Attribution — CoMapeo SMP Renderer

AwanaGIS vendors the minimal tile-generation and SMP archive engine from
`digidem/qgis-smp-plugin` (CoMapeo Map Builder) so users can export CoMapeo
offline `.smp` packages without installing a second QGIS plugin.

## Upstream Provenance

- **Repository:** <https://github.com/digidem/qgis-smp-plugin>
- **Pinned Commit:** `34715788e94718d036a58f9992d7ef69b9ecf3d5`
- **Upstream Version (`metadata.txt`):** `0.9.0`
- **Copyright:** Copyright (c) 2026 Awana Digital
- **License:** MIT License (full text preserved in [`vendor/LICENSE`](./vendor/LICENSE))

## Vendored Files

| Local Path | Upstream Path | Upstream SHA-256 | Local SHA-256 |
|---|---|---|---|
| `integrations/smp/vendor/comapeo_smp_generator.py` | `comapeo_smp_generator.py` | `629aaa46f84ea085cb561eb5ae293262cc7b00f2fd6d4372ff30e4c096bf1314` | `9b59fc309d9feed27cf5aec2c058ac88787809ef6aa77b0610d8897b20b02944` |
| `integrations/smp/vendor/LICENSE` | `LICENSE` | `e28d3618123a460b2ad1fbdee9c548c1b859da8546675eeec7230210387f0d9e` | `e28d3618123a460b2ad1fbdee9c548c1b859da8546675eeec7230210387f0d9e` |

## Local Adaptations

1. **Mandatory ordered render-layer allowlist seam (`render_layers`):**
   - Added optional `render_layers=None` parameter to
     `SMPGenerator.generate_smp_from_canvas` and
     `SMPGenerator._generate_tiles_from_canvas`.
   - When `render_layers is not None`, rendering uses that explicit ordered
     layer list instead of querying `_visible_layers_in_render_order(project)`,
     and fails closed (`ValueError`) if the allowlist is empty.
   - This guarantees `blocked_sensitive` and unapproved `restricted` layers
     cannot enter tile rendering even while visible on the QGIS map canvas.
2. **Isolated `QgsProject` snapshot seam (`project=None`):**
   - Added optional `project=None` parameter to `SMPGenerator.__init__` and
     routed project metadata/CRS lookups through `self._get_project()`, so
     background `QgsTask` exports run against a main-thread-cloned project
     and cloned layers rather than live GUI-owned `QgsProject.instance()`.
3. **Fail closed on layer render errors (`job.errors()`):**
   - `_render_single_tile` inspects `QgsMapRendererCustomPainterJob.errors()`
     immediately after `waitForFinished()`; any reported layer/provider render
     errors raise `RuntimeError` rather than saving or caching blank/partial
     tiles.
4. **Python 3.8/3.9 compatibility (`from __future__ import annotations`):**
   - Added postponed annotation evaluation for QGIS 3.22+ runtimes.
5. **No duplicate UI / Processing provider:**
   - Upstream `comapeo_smp.py`, `comapeo_smp_provider.py`,
     `comapeo_smp_algorithm.py`, and `comapeo_smp_dialog.py` are **not**
     vendored or registered, ensuring full coexistence if the standalone
     `comapeo_smp` plugin is installed alongside AwanaGIS.
