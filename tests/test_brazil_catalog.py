"""Offline catalog, bilingual search, area resolution, and tool-contract tests."""

from importlib import import_module
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from qgis.core import QgsApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

PKG = ROOT.name
catalog = import_module(f"{PKG}.integrations.brazil.catalog")
manifest = import_module(f"{PKG}.integrations.brazil.manifest")
resolver = import_module(f"{PKG}.integrations.brazil.resolver")
br_tools = import_module(f"{PKG}.integrations.brazil.tools")
core_tools = import_module(f"{PKG}.core.tools")
formatting = import_module(f"{PKG}.gui.formatting")


class _FakeHttpResp:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class BrazilCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def test_merged_catalog_counts_uniqueness_and_mandatory_sources(self):
        entries = catalog.get_catalog()
        raw_gisbr = catalog.GISBR_RAW_SOURCES
        self.assertEqual(len(raw_gisbr), 76)
        self.assertEqual(len(manifest.CURATED_INDIGENOUS_SOURCES), 14)
        self.assertEqual(len(entries), 90)

        ids = [e["source_id"] for e in entries]
        self.assertEqual(len(ids), len(set(ids)))

        mandatory = {
            "geobr_terras_indigenas",
            "funai_ti_boundaries",
            "funai_dsei_areas",
            "inpe_prodes",
            "inpe_deter",
            "ibge_indigenous_localities_2022",
            "funai_indigenous_villages",
            "isa_territories",
            "mapi_isolated_peoples",
            "raisg_indigenous_territories",
            "mapbiomas_alerta",
            "icmbio_uc",
            "anm_sigmine",
            "sicar_imoveis",
        }
        self.assertTrue(mandatory.issubset(set(ids)))

        for sid in mandatory:
            entry = catalog.get_source(sid)
            self.assertIsNotNone(entry, sid)
            self.assertIn(entry["origin_class"], manifest.ORIGIN_CLASSES)
            self.assertIn(entry["loader_state"], manifest.LOADER_STATES)
            self.assertIn(entry["load_policy"], manifest.LOAD_POLICIES)
            self.assertIn(entry["sensitivity"], manifest.SENSITIVITY_LEVELS)

        # Verify distinct official vs mirror vs non-government classification
        self.assertEqual(catalog.get_source("funai_ti_boundaries")["origin_class"], "official_direct")
        self.assertEqual(catalog.get_source("funai_dsei_areas")["origin_class"], "official_direct")
        self.assertEqual(catalog.get_source("inpe_prodes")["origin_class"], "official_direct")
        self.assertEqual(catalog.get_source("inpe_deter")["origin_class"], "official_direct")
        self.assertEqual(catalog.get_source("geobr_terras_indigenas")["origin_class"], "official_mirror")
        self.assertEqual(catalog.get_source("isa_territories")["origin_class"], "non_government")
        self.assertEqual(catalog.get_source("mapi_isolated_peoples")["origin_class"], "non_government")
        self.assertEqual(catalog.get_source("raisg_indigenous_territories")["origin_class"], "non_government")
        self.assertEqual(catalog.get_source("mapbiomas_alerta")["origin_class"], "non_government")
        self.assertEqual(catalog.get_source("mapbiomas_cobertura")["origin_class"], "non_government")

    def test_offline_bilingual_search_and_filters(self):
        queries_and_expected = [
            ("terras indígenas", "funai_ti_boundaries"),
            ("terras indigenas", "geobr_terras_indigenas"),
            ("indigenous lands", "funai_ti_boundaries"),
            ("DSEI", "funai_dsei_areas"),
            ("SESAI", "funai_dsei_areas"),
            ("PRODES", "inpe_prodes"),
            ("DETER", "inpe_deter"),
            ("povos isolados", "mapi_isolated_peoples"),
            ("isolated peoples", "mapi_isolated_peoples"),
            ("aldeias", "funai_indigenous_villages"),
            ("localidades indígenas", "ibge_indigenous_localities_2022"),
            ("ISA", "isa_territories"),
            ("RAISG", "raisg_indigenous_territories"),
            ("MapBiomas Alerta", "mapbiomas_alerta"),
            ("unidades de conservação", "icmbio_uc"),
            ("processos minerários", "anm_sigmine"),
            ("imóveis rurais", "sicar_imoveis"),
        ]
        for query, expected_id in queries_and_expected:
            with self.subTest(query=query, expected_id=expected_id):
                res = br_tools.br_search_sources(query=query, limit=30)
                self.assertTrue(res["ok"])
                found_ids = {s["id"] for s in res["sources"]}
                self.assertIn(expected_id, found_ids)

        # Publisher filter mapping: official -> official_direct; official_mirror preserved separately
        res_off = br_tools.br_search_sources(query="terras indígenas", publisher_type="official")
        self.assertTrue(all(s["origin_class"] == "official_direct" for s in res_off["sources"]))
        self.assertIn("funai_ti_boundaries", {s["id"] for s in res_off["sources"]})

        res_mir = br_tools.br_search_sources(query="terras indígenas", publisher_type="official_mirror")
        self.assertTrue(all(s["origin_class"] == "official_mirror" for s in res_mir["sources"]))
        self.assertIn("geobr_terras_indigenas", {s["id"] for s in res_mir["sources"]})

        res_bad_pub = br_tools.br_search_sources(publisher_type="bogus_type")
        self.assertFalse(res_bad_pub["ok"])

        # UF filtering: df_escolas_publicas only for DF
        res_df = br_tools.br_search_sources(query="escolas", uf="DF")
        self.assertIn("df_escolas_publicas", {s["id"] for s in res_df["sources"]})
        res_pa = br_tools.br_search_sources(query="escolas", uf="PA")
        self.assertNotIn("df_escolas_publicas", {s["id"] for s in res_pa["sources"]})

        # Sensitivity filter & loadable_only exclusion
        res_blocked = br_tools.br_search_sources(sensitivity="blocked_isolated_peoples")
        self.assertEqual([s["id"] for s in res_blocked["sources"]], ["mapi_isolated_peoples"])
        res_loadable = br_tools.br_search_sources(query="povos isolados", loadable_only=True)
        self.assertNotIn("mapi_isolated_peoples", {s["id"] for s in res_loadable["sources"]})

    def test_source_details_offline_and_bounded_probe(self):
        # Offline details (probe=False) must never call urlopen
        with patch.object(catalog.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
            res = br_tools.br_source_details(
                ["funai_dsei_areas", "mapbiomas_cobertura", "raisg_indigenous_territories"],
                probe=False,
            )
            self.assertTrue(res["ok"])
            by_id = {s["source_id"]: s for s in res["sources"]}
            self.assertIn("NOT TI legal demarcation", " ".join(by_id["funai_dsei_areas"]["caveats"]))
            self.assertEqual(by_id["mapbiomas_cobertura"]["data_year"], 2023)
            self.assertEqual(by_id["raisg_indigenous_territories"]["status"], "portal_only")

        # Unknown ID returns ok=False cleanly
        res_unk = br_tools.br_source_details(["nonexistent_source_xyz"])
        self.assertFalse(res_unk["ok"])
        self.assertEqual(res_unk["unknown_source_ids"], ["nonexistent_source_xyz"])

        # Large (>32 KB) GetCapabilities probe verifies typename near end of XML
        catalog._PROBE_CACHE.clear()
        padding = "<!-- pad -->" * 4000  # ~48 KB
        caps_xml = (
            f"<WFS_Capabilities>{padding}"
            "<FeatureTypeList><FeatureType><Name>prodes-legal-amz:yearly_deforestation</Name></FeatureType></FeatureTypeList>"
            "</WFS_Capabilities>"
        ).encode("utf-8")
        with patch.object(catalog.urllib.request, "urlopen", return_value=_FakeHttpResp(caps_xml)):
            res_probe = br_tools.br_source_details(["inpe_prodes"], probe=True)
            self.assertTrue(res_probe["ok"])
            src = res_probe["sources"][0]
            self.assertEqual(src["status"], "reachable")
            self.assertTrue(src["machine_access_verified"])
            self.assertTrue(src["probe"]["typename_verified"])

    def test_area_resolver_ibge_disambiguation_and_ti_vs_dsei(self):
        # Valid 7-digit IBGE code
        sfx = br_tools.br_resolve_area(type="municipality", ibge_code="1507300")
        self.assertTrue(sfx["ok"])
        self.assertEqual(sfx["status"], "resolved")
        self.assertEqual(sfx["area"]["name"], "São Félix do Xingu")
        self.assertEqual(sfx["area"]["uf"], "PA")

        # Invalid IBGE code rejected
        bad = br_tools.br_resolve_area(type="municipality", ibge_code="9999999")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["status"], "invalid_ibge_code")

        short = br_tools.br_resolve_area(type="municipality", ibge_code="12345")
        self.assertFalse(short["ok"])
        self.assertEqual(short["status"], "invalid_ibge_code")

        # Multi-UF ambiguity for common municipality name
        ambig = br_tools.br_resolve_area(type="municipality", name="Alto Paraíso")
        self.assertTrue(ambig["ok"])
        self.assertEqual(ambig["status"], "ambiguous")
        self.assertTrue(ambig["needs_disambiguation"])
        ufs = {c["uf"] for c in ambig["candidates"]}
        self.assertTrue({"PR", "RO"}.issubset(ufs))

        ambig2 = br_tools.br_resolve_area(type="municipality", name="Bom Jesus")
        self.assertTrue(ambig2["ok"])
        self.assertEqual(ambig2["status"], "ambiguous")
        self.assertGreaterEqual(len({c["uf"] for c in ambig2["candidates"]}), 4)

        # Disambiguated with UF
        resolved = br_tools.br_resolve_area(type="municipality", name="Alto Paraíso de Goiás", uf="GO")
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["area"]["ibge_code"], "5200605")

        # State and regional resolution
        st = br_tools.br_resolve_area(type="state", uf="PA")
        self.assertTrue(st["ok"])
        self.assertEqual(st["area"]["recorte_type"], "uf")
        self.assertGreater(len(st["area"]["codes"]), 100)

        rm = br_tools.br_resolve_area(type="metropolitan_region", name="Belém")
        self.assertTrue(rm["ok"])
        self.assertEqual(rm["area"]["recorte_type"], "rm")

        # Named-TI resolution: multi-UF Yanomami + Guarani ambiguity + DSEI concept mismatch
        ti_yan = br_tools.br_resolve_area(type="indigenous_territory", name="Yanomami")
        self.assertTrue(ti_yan["ok"])
        self.assertEqual(ti_yan["status"], "needs_reference_data")
        self.assertEqual(ti_yan["area"]["terrai_cod"], "51901")
        self.assertTrue(ti_yan["area"]["cross_uf"])
        self.assertEqual(ti_yan["area"]["ufs"], ["AM", "RR"])

        ti_gua = br_tools.br_resolve_area(type="indigenous_territory", name="Guarani")
        self.assertTrue(ti_gua["ok"])
        self.assertEqual(ti_gua["status"], "ambiguous")
        self.assertGreaterEqual(len(ti_gua["candidates"]), 2)

        dsei_err = br_tools.br_resolve_area(
            type="indigenous_territory",
            name="Yanomami",
            source_id="funai_dsei_areas",
        )
        self.assertFalse(dsei_err["ok"])
        self.assertEqual(dsei_err["status"], "concept_mismatch")

    def test_tool_specs_and_formatting_parity(self):
        expected_names = {
            "br_search_sources",
            "br_source_details",
            "br_resolve_area",
            "br_plan_load",
            "br_execute_load",
        }
        self.assertTrue(expected_names.issubset(set(core_tools.TOOL_BY_NAME.keys())))
        self.assertTrue(expected_names.issubset({s["name"] for s in core_tools.tool_specs(include_gee=False)}))
        self.assertTrue(expected_names.issubset({s["name"] for s in core_tools.anthropic_tool_list(include_gee=True)}))

        exec_spec = core_tools.TOOL_BY_NAME["br_execute_load"]
        self.assertEqual(list(exec_spec["input_schema"]["properties"].keys()), ["plan_id"])
        self.assertFalse(exec_spec["input_schema"].get("additionalProperties", True))

        for name in expected_names:
            label = formatting.humanize_tool_name(name)
            self.assertTrue(label)
            self.assertNotIn("_", label)


if __name__ == "__main__":
    unittest.main()
