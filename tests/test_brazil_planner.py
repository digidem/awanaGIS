"""Plan ID binding and mask-host disclosure tests for the Brazil planner."""

from importlib import import_module
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

planner = import_module(f"{ROOT.name}.integrations.brazil.planner")


def _plan(area, source="inpe_deter"):
    with patch.object(planner, "_existing_gpkg_layers", return_value=set()):
        return planner.plan_load([source], area, output_gpkg="/tmp/awana_plan_test.gpkg")


class PlannerTests(unittest.TestCase):
    def setUp(self):
        planner.clear_plans()

    def test_plan_id_binds_bbox_wkt_and_territory(self):
        base = {"type": "municipality", "id": "1100015", "codes": ["1100015"], "bbox": [-62.0, -12.0, -61.0, -11.0]}
        a = _plan(base)
        self.assertTrue(a["can_execute"], a)
        variants = [
            dict(base, bbox=[-62.0, -12.0, -60.0, -11.0]),
            dict(base, geometry_wkt="POLYGON((0 0,1 0,1 1,0 0))"),
            dict(base, terrai_cod="123"),
        ]
        ids = {a["plan_id"]}
        for v in variants:
            ids.add(_plan(v)["plan_id"])
        self.assertEqual(len(ids), 4)
        frozen, err = planner.get_frozen_plan(a["plan_id"])
        self.assertIsNone(err)
        self.assertEqual(frozen["area"]["bbox"], base["bbox"])
        self.assertEqual(_plan(base)["plan_id"], a["plan_id"])

    def test_mask_hosts_listed_without_wkt(self):
        area = {"type": "municipality", "id": "1100015", "codes": ["1100015"]}
        res = _plan(area)
        self.assertTrue(res["can_execute"], res)
        self.assertIn("www.ipea.gov.br", res["hosts"])
        self.assertIn("github.com", res["hosts"])
        frozen, _ = planner.get_frozen_plan(res["plan_id"])
        self.assertIn("www.ipea.gov.br", frozen["hosts"])

    def test_mask_hosts_listed_with_wkt_because_loader_can_fall_back_remote(self):
        # A nonempty WKT only avoids the remote mask when it parses into a usable polygon;
        # loader._mask_layer_from_area otherwise falls back to the IPEA/GitHub boundary fetch
        # for municipality/aggregate area types, so the hosts must stay disclosed.
        area = {
            "type": "municipality",
            "id": "1100015",
            "codes": ["1100015"],
            "geometry_wkt": "POLYGON((0 0,1 0,1 1,0 0))",
        }
        res = _plan(area)
        self.assertTrue(res["can_execute"], res)
        self.assertIn("www.ipea.gov.br", res["hosts"])
        self.assertIn("github.com", res["hosts"])
        frozen, _ = planner.get_frozen_plan(res["plan_id"])
        self.assertIn("www.ipea.gov.br", frozen["hosts"])

    def test_no_remote_mask_hosts_for_wkt_only_area_type(self):
        # project_layer areas have no Recorte, so the loader never fetches a remote mask.
        area = {"type": "project_layer", "id": "x", "geometry_wkt": "POLYGON((0 0,1 0,1 1,0 0))"}
        res = _plan(area)
        self.assertTrue(res["can_execute"], res)
        self.assertNotIn("www.ipea.gov.br", res["hosts"])

    def test_frozen_plan_area_is_isolated_from_later_mutation(self):
        area = {"type": "municipality", "id": "1100015", "codes": ["1100015"], "bbox": [-62.0, -12.0, -61.0, -11.0]}
        res = _plan(area)
        self.assertTrue(res["can_execute"], res)
        original_payload = (list(area["bbox"]), list(area["codes"]))

        # Mutating the caller's area after planning must not change the frozen plan.
        area["bbox"][0] = -50.0
        area["codes"].append("9999999")
        frozen, err = planner.get_frozen_plan(res["plan_id"])
        self.assertIsNone(err)
        self.assertEqual(frozen["area"]["bbox"], original_payload[0])
        self.assertEqual(frozen["area"]["codes"], original_payload[1])

        # Mutating a returned plan must not leak back into the store.
        frozen["area"]["bbox"][1] = 0.0
        frozen["area"]["codes"].append("8888888")
        again, err = planner.get_frozen_plan(res["plan_id"])
        self.assertIsNone(err)
        self.assertEqual(again["area"]["bbox"], original_payload[0])
        self.assertEqual(again["area"]["codes"], original_payload[1])


if __name__ == "__main__":
    unittest.main()
