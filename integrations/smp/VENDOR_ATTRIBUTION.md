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
| `integrations/smp/vendor/comapeo_smp_generator.py` | `comapeo_smp_generator.py` | `629aaa46f84ea085cb561eb5ae293262cc7b00f2fd6d4372ff30e4c096bf1314` | `e2f5bf4705d86ebab4ae4baae29c5ad05a1ceb03f24ee8328534fcfcd7cc67fc` |
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
2. **No duplicate UI / Processing provider:**
   - Upstream `comapeo_smp.py`, `comapeo_smp_provider.py`,
     `comapeo_smp_algorithm.py`, and `comapeo_smp_dialog.py` are **not**
     vendored or registered, ensuring full coexistence if the standalone
     `comapeo_smp` plugin is installed alongside AwanaGIS.
