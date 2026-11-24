> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# brand-guide.md — AwanaGIS application of Awana Digital branding

**Product:** AwanaGIS (a product by Awana Digital)  
**Official source:** [Awana Digital Branding Guidelines, Notion](https://app.notion.com/p/3341b08162d580a38611ce745e372f45)  
**Retrieved:** 2026-11-23  
**Scope:** Self-contained brand handoff for a developer implementing an accessible QGIS desktop plugin, not a replacement for approved source files or design-team signoff.

## 1. Verified from the official guideline — not suggestions

The Awana Digital guideline says its brand is evolving and provides visual resources for implementation. It shows **rectangle, circle, square and wordmark-only** Awana Digital logo variations in Burgundy, Earth, Black and (for the wordmark) White; example imagery and brand illustrations. Use the actual hosted source/approved asset—not a recreation from memory—when incorporating company logo artwork.

### Exact color palette

| Category | Official name | HEX | Intended handling in this plugin |
|---|---|---|---|
| Primary | AD Dark Burgundy | `#6B0030` | Strong brand and high-contrast text/action color |
| Primary | AD Burgundy | `#8D003E` | Primary identity and action emphasis |
| Primary | AD Earth | `#932D00` | Restrained warm accent |
| Secondary | AD Pink | `#FF60C0` | Decorative emphasis and carefully labelled signals |
| Secondary | AD Orange | `#FF8D00` | Attention accent, never unreadable text |
| Secondary | AD Pollen | `#FFE460` | Warm highlight on a sufficiently dark surface |
| Secondary | AD Fungi | `#00D05F` | High-energy positive accent with text/icon label |
| Secondary | AD Forest | `#148658` | Contextual accent, verify contrast |
| Secondary | AD Cream | `#FDF7EF` | Friendly light background/surface proposal |
| Secondary | AD River | `#0063A1` | Calm accent/link/data-category proposal |
| Secondary | AD Sky | `#0094FF` | Info/selection accent, verify contrast |
| Secondary | AD Rain | `#B4DDF9` | Muted highlight/background proposal |

**Exact HEX values are official.** The rightmost column is **our proposed AwanaGIS usage**, not a statement that the Notion guidelines prescribe UI role assignments.

### Official font families and roles

| Typeface | Guideline role | AwanaGIS application |
|---|---|---|
| **Tomorrow** | Cover titles, big text, large slide titles, occasional body text | Main product title, large welcome/section headings, sparse hero typography |
| **Public Sans** | Running/body text | Chat and tool content, forms, processing results, confirmations, accessibility-first readable text |
| **Space Grotesk** | Small text and captions | Compact metadata, badges/chips, captions, footers, hints and labels |

The guideline links font ZIP files. Check licenses and the chosen packaging approach. QGIS is a desktop product with OS font variability: the plugin **must remain usable without external font installation** using a fallback stack (system UI sans-serif / QGIS default). If font files are included in a final distributable, include the required license and source attribution. Do not provide font files outside the authorized project/release artifacts.

### Logo assets visible on the source page

- Rectangle logo: Burgundy, Earth, Black; a Dark Burgundy tag example is also shown.
- Circle logo: Burgundy, Earth, Black.
- Square logo: Burgundy, Earth, Black.
- Wordmark-only: Burgundy, Earth, Black, White.
- Example posters and hero layouts provide stylistic references (illustration, compositions, color relationships).

**Do not assume a specific AwanaGIS logo exists yet.** Do not simply relabel or mutate the approved Awana Digital wordmark. Design a distinctive AwanaGIS symbol and lockup as a *proposal* consistent with the parent brand; obtain design approval before declaring it approved or publishing it as such. Record the source of every asset used.

## 2. AwanaGIS-specific design recommendations — require design review

These choices follow the guideline but are **not themselves prescribed** by it.

- **Primary light surfaces:** AD Cream `#FDF7EF` with Dark Burgundy text `#6B0030`; neutral QGIS/system text may also be used for readability. Let QGIS supply native controls where a custom theme would reduce usability.
- **Primary action:** Dark Burgundy or Burgundy fill with cream/white label; ensure hover/disabled/focus contrast and no color-only cues.
- **Secondary accents:** AD Earth, River and Forest; reserve bright Pink, Orange, Sky, Fungi and Pollen for limited callouts, map/category swatches and emphasis with visible text or pictograms.
- **Layout:** clean hierarchy, roomy but not oversized chat bubbles, minimal header, precise geospatial terminology and restrained animation. Small docks and Qt default sizes matter more than decorative graphics.
- **Icon concept to explore (NOT an approved logo):** topology/contour linework, woven map layers or a compact geography mark that remains recognizable at 16–24px. Avoid clichéd generic AI robots and avoid copying a restricted Indigenous cultural motif.
- **Dark mode:** use QGIS/system theme-compatible dark surfaces and carefully derived high-contrast semantic tokens. **Do not** claim any invented dark neutrals are official Awana colors. Test real dark QGIS palettes rather than blindly forcing cream everywhere.
- **Map and layer symbology:** the QGIS map canvas, thematic layers, basemap, Indigenous territory datasets, choropleths and SMP output are **user data**, not a space to impose brand colors. Do not recolor them during rebranding.
- **New UI surfaces:** `br_*` source explorer, Indigenous-data governance notices and `smp_*` export estimator should share the same buttons, form treatment, progress and error states—**if implemented**. Do not claim these features exist merely because their specs were written.

## 3. Contrast results, calculated from the exact brand HEX codes

WCAG 2.x normal-text contrast criterion is at least 4.5:1; 3:1 applies to large text and key non-text UI graphics. Contrast must be rechecked in both themes and all interactive states.

| Foreground on background | Approximate ratio | Normal text? |
|---|---:|---|
| AD Dark Burgundy `#6B0030` on AD Cream `#FDF7EF` | **11.83:1** | Yes |
| AD Burgundy `#8D003E` on AD Cream | **8.96:1** | Yes |
| AD Earth `#932D00` on AD Cream | **7.54:1** | Yes |
| AD River `#0063A1` on AD Cream | **5.98:1** | Yes |
| AD Forest `#148658` on AD Cream | **4.31:1** | No for normal-size text |
| AD Pink `#FF60C0` on AD Cream | **2.57:1** | No |
| AD Orange `#FF8D00` on AD Cream | **2.18:1** | No |
| AD Pollen `#FFE460` on AD Dark Burgundy | **9.90:1** | Yes |

**Do not assume one color can stand for sensitive information:** errors, security approvals, slow downloads, missing data and protected Indigenous locations must use text labels and/or icons as well as color.

## 4. Desktop QGIS implementation details

- Implement `gui/brand.py` or `ui/theme_tokens.py` as the single source for semantic UI tokens, referencing `brand-tokens.json`. Keep **official palette** immutable; compute light/dark usage separately.
- Use local widget-level or object-name-scoped Qt stylesheets; **never** style global QGIS windows or the user's canvas. Prefer Qt/QGIS native widgets and accessibility support.
- Make typography configurable/responsive: keep original QGIS font scale settings, use the chosen brand families where present and fallback gracefully; preserve Unicode/PT-BR glyph coverage.
- Check each element in QGIS 3 Qt5 and QGIS 4 Qt6 as available. Validate compact dock, 100/125/150/200% OS scaling, keyboard navigation and screen reader names.
- Show `AwanaGIS` as the product name, `by Awana Digital` as a supporting credit when appropriate, never as a replacement for legal authorship of upstream code.
- Do not erase upstream AgenticGIS/GISBR/SMP attribution from About and NOTICE; rebrand identity does not rewrite license history.
- Materialize/safely acquire official logos from Notion only if authorized; do not commit expiring signed Notion URLs, authentication tokens or unlicensed resources. Save approved artwork locally in the **source repository** with documented provenance and license; don't depend on Notion at runtime.

## 5. QA / review checklist

- [ ] Source colors match official HEX values exactly (check exact JSON tokens).
- [ ] Font family hierarchy matches Notion and falls back cleanly.
- [ ] Product icon and wordmark are distinct from Awana Digital's parent logos, with draft/approval status recorded.
- [ ] Toolbar, dock, settings, chat, dialogs, progress, catalogs and exporters (if present) share consistent design tokens.
- [ ] Light, dark, high contrast, hover, keyboard focus, disabled and warning states are understandable.
- [ ] Portuguese accents and long labels render without truncation; English also works.
- [ ] No unintended change to maps, user symbology or exported SMP raster appearances.
- [ ] Screenshots (light/dark, PT-BR/EN and key states) are reviewed by the Awana Digital design team prior to public release.
- [ ] Asset licensing/provenance and any included font licenses are documented.

## References and change tracking

- **Authoritative Notion page:** https://app.notion.com/p/3341b08162d580a38611ce745e372f45
- **Official source status:** project marked Completed in Notion; the page itself still describes brand evolution. A newer revision of the source may supersede this extracted snapshot.
- **Snapshot date:** 2026-11-23. If working later, developer should re-fetch and compare before changing visual tokens.
