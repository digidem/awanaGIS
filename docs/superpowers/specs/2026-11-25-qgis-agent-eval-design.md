# AwanaGIS evaluation design

The evaluation measures whether an Indigenous community mapper with limited experience using digital tools can complete a map in AwanaGIS using everyday Brazilian Portuguese. The workflow starts with a basemap and GeoJSON files and ends with a PDF and a CoMapeo map for offline use. Validate prompt wording and the clarity of replies with intended users or community facilitators. Start with synthetic data so the fixtures and traces can be shared without exposing community locations.

## Cases

| User request or action | Observable result |
|---|---|
| “Coloca um mapa de fundo.” | Google Satellite is selected by default. An explicit alternative wins. If the requested source is unavailable, the agent explains the problem before substituting imagery. |
| “Abre esses arquivos e me explica o que tem neles.” | The supplied GeoJSON layers load. The reply gives a plain-language explanation grounded in the loaded layers, with accurate counts and examples. Unknown field meanings stay explicit. |
| “Deixa as aldeias em azul, troca o símbolo e mostra os nomes.” | The correct layer has the requested color and symbol. Labels use the appropriate name field and a white buffer by default. |
| “Mostra só as aldeias com escola e junta com essa tabela.” | The result contains the expected records and joined fields. The agent explains missing matches or ambiguous keys in plain language and preserves the original data unless the user requested edits. |
| “Faz um PDF desse mapa pra reunião.” | The PDF opens and uses the intended extent and layers. Check the title, scale bar, north arrow, and legend or source credits where applicable. Inspect a rendered page for readability and clipping. |
| “Cria um mapa para o Mapeo.” | The agent identifies the territory, guides the user to frame a specific area if they want more detail there, explains the likely file size and preparation time, and creates an `.smp` file that opens offline in CoMapeo and preserves the visible map’s styling and layers. |

Run the cases independently from prepared QGIS projects and together in one conversation. Include short follow-ups that refer to the previous layer or map. Score unnecessary questions separately from questions that resolve real ambiguity.

## Offline map

Build the SMP with three coverage bands:

| Coverage | Typical zooms | How to choose the extent |
|---|---|---|
| World | 1–5 | Include a world overview for orientation. |
| Territory | 6–11 | Use an unambiguous territory boundary from the loaded layers or conversation. Ask which territory to include if the available context is unclear. |
| Specific region | 12 up to 14–18 | Include this band when the user has a specific area of interest. Use the QGIS canvas to frame the area, and recommend the maximum zoom based on the needed detail, available imagery, file size, and preparation time. |

For the case with a specific region, start with the territory in view. Say “Aproxime e mova o mapa até aparecer na tela toda a área que você quer ver com mais detalhes. Quando estiver do jeito que você quer, me diga ‘pronto’.” The test driver pans and zooms before replying. Capture the extent and visible layers from the updated canvas. When the user explicitly asks to use the area already on screen for more detail, use that view directly. The territory keeps its wider coverage at zooms 6–11. Include a territory-only case with no high-detail band and an ambiguous-territory case that requires a targeted question.

Recommend how far the user can zoom in on the offline map and explain the tradeoff between detail, file size, and preparation time. Base the estimates on the selected area, zoom range, and available imagery. Report ranges with their assumptions and record actual bytes and elapsed export time. If the user changes the view or zoom range, refresh the estimate before exporting.

Use a pinned release of [CoMapeo Map Builder](https://plugins.qgis.org/plugins/comapeo_smp/) in the main benchmark while native SMP support is on the roadmap. Use a local raster basemap fixture for repeatability. Check coverage and zoom limits for each band at tile boundaries, including whether high zooms follow the updated canvas extent. Render representative tiles to check the basemap, visible layers, styling, and labels. Verify import and viewing in CoMapeo offline in the Desktop acceptance pass.

Exercise the missing-plugin flow separately. Offer to install CoMapeo Map Builder from the QGIS Plugin Repository in plain PT-BR. On approval, install the specific plugin, verify it loads, then resume the export flow. Test approval, refusal, and install failure in a disposable profile. Agent-driven installation remains proposed behavior.

## Runner and scoring

Start with one pinned backend and model through the normal AwanaGIS request path. Use fresh sessions, synthetic projects, and per-run output directories. Run QGIS headlessly for state and artifact checks. Use Desktop for the view-selection interaction, rendered layout, and plugin installation. The deterministic checks inspect QGIS state and files. A Portuguese-speaking reviewer samples replies for whether users can understand what happened and what to do next.

Report correctness and unintended changes first. For correct runs, compare time to first useful feedback, time to completion, model requests, QGIS tool calls, failed or repeated calls, and clarification turns. Record model and export time separately, as well as time waiting for scripted user actions. Keep traces sufficient to attribute failures and avoid storing credentials or real community data.

## Improvement loop

1. Run each baseline case three times and report per-case pass counts. Keep prompt and fixture variants out of tuning for use in the promotion check.
2. Use the traces to pick one recurring failure or source of wasted work. Likely first candidates are the basemap and label defaults, layer and field summaries, and the handoff from canvas selection to SMP estimation.
3. Rerun the affected cases against the same baseline configuration. Repeat promising changes across the full workflow and held-back variants. Keep changes that preserve correctness and user control and show a repeatable gain in the intended metric.
4. Keep deterministic regressions in the offline suite. Run live model comparisons when tuning the agent and when evaluating changes to models, prompts, or tools.
