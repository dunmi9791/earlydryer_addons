# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json

from odoo.tests import tagged

from .common import CatalogCommon

PLAIN = (str, int, float, bool, type(None))


@tagged("post_install", "-at_install")
class TestCatalogForBranch(CatalogCommon):
    def _assert_plain(self, value, path="result"):
        if isinstance(value, dict):
            for key, sub in value.items():
                self.assertIsInstance(key, str, path)
                self._assert_plain(sub, f"{path}.{key}")
        elif isinstance(value, list):
            for index, sub in enumerate(value):
                self._assert_plain(sub, f"{path}[{index}]")
        else:
            self.assertIsInstance(value, PLAIN, path)

    def test_json_serialisable(self):
        result = self.Catalog.catalog_for_branch(self.branch_1, "walk_in")
        self._assert_plain(result)
        json.dumps(result)

    def test_content(self):
        result = self.Catalog.catalog_for_branch(self.branch_1, "walk_in")
        shirt = next(c for c in result if c["code"] == "TSHIRT")
        self.assertEqual(shirt["group"], "tops")
        services = {s["code"]: s for s in shirt["services"]}
        self.assertEqual(set(services) & {"TWI", "TDC", "TRUGC"}, {"TWI", "TDC"})
        wash_iron = services["TWI"]
        self.assertEqual(wash_iron["price"], 1000)
        self.assertEqual(wash_iron["turnaround_hours"], 16)
        self.assertTrue(wash_iron["express_available"])
        self.assertEqual(wash_iron["express_turnaround_hours"], 4)
        self.assertEqual(wash_iron["express_price"], 500)
        self.assertEqual(services["TDC"]["express_price"], 700)
        surcharges = {s["code"]: s for s in wash_iron["surcharges"]}
        self.assertEqual(surcharges["TBEAD"]["price"], 500)
        self.assertEqual(surcharges["TSILK"]["price"], 250)
        rug = next(c for c in result if c["code"] == "TRUG")
        rug_services = {s["code"]: s for s in rug["services"]}
        self.assertIsNone(rug_services["TRUGC"]["express_price"])
        # silk is restricted to shirts
        self.assertNotIn(
            "TSILK", {s["code"] for s in rug_services["TRUGC"]["surcharges"]}
        )

    def test_archived_service_hidden(self):
        self.svc_dc.action_archive()
        result = self.Catalog.catalog_for_branch(self.branch_1, "walk_in")
        shirt = next(c for c in result if c["code"] == "TSHIRT")
        self.assertNotIn("TDC", {s["code"] for s in shirt["services"]})
