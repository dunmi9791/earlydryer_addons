# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CatalogCommon


@tagged("post_install", "-at_install")
class TestPriceItem(CatalogCommon):
    def _price(self, product, **kwargs):
        return self.Catalog.price_item(
            product, False, self.branch_1, "walk_in", **kwargs
        )

    def test_base_price(self):
        result = self._price(self.shirt_wi)
        self.assertEqual(result["pricelist_id"], self.pl_walk_in_b1.id)
        self.assertEqual(result["unit_price"], 1000)
        self.assertEqual(result["surcharge_lines"], [])
        self.assertIsNone(result["express_line"])
        self.assertEqual(result["total"], 1000)

    def test_fixed_and_percent_surcharges_and_express_percent(self):
        result = self._price(
            self.shirt_wi,
            surcharges=self.sur_beads | self.sur_silk,
            express=True,
            quantity=2,
        )
        lines = {line["surcharge_id"]: line for line in result["surcharge_lines"]}
        # fixed: price of the surcharge product in the same price list
        self.assertEqual(lines[self.sur_beads.id]["unit_price"], 500)
        self.assertEqual(
            lines[self.sur_beads.id]["product_id"], self.sur_beads.product_id.id
        )
        # percent: of the garment unit price
        self.assertEqual(lines[self.sur_silk.id]["unit_price"], 250)
        self.assertEqual(
            result["express_line"],
            {"product_id": self.Catalog.get_express_product().id, "unit_price": 500},
        )
        self.assertEqual(result["total"], (1000 + 500 + 250 + 500) * 2)

    def test_fixed_surcharge_without_item_uses_product_price(self):
        other = self.Pricelist.create(
            {"name": "T Pickup B1", "earlydryer_channel": "pickup",
             "earlydryer_branch_id": self.branch_1.id}
        )  # fmt: skip
        result = self.Catalog.price_item(
            self.shirt_wi, False, self.branch_1, "pickup", surcharges=self.sur_beads
        )
        self.assertEqual(result["pricelist_id"], other.id)
        self.assertEqual(result["unit_price"], 100)
        self.assertEqual(result["surcharge_lines"][0]["unit_price"], 300)

    def test_express_fixed(self):
        result = self._price(self.shirt_dc, express=True)
        self.assertEqual(result["unit_price"], 2000)
        self.assertEqual(result["express_line"]["unit_price"], 700)
        self.assertEqual(result["total"], 2700)

    def test_rounding(self):
        self.sur_silk.percent = 33.3333
        result = self._price(self.shirt_wi, surcharges=self.sur_silk, quantity=3)
        silk = result["surcharge_lines"][0]["unit_price"]
        self.assertEqual(silk, self.currency.round(333.333))
        self.assertEqual(result["total"], self.currency.round((1000 + silk) * 3))

    def test_express_not_available(self):
        with self.assertRaises(UserError):
            self._price(self.rug_rug, express=True)

    def test_surcharge_not_applicable(self):
        # silk is restricted to the shirt category
        with self.assertRaises(UserError):
            self._price(self.rug_rug, surcharges=self.sur_silk)

    def test_price_check_wizard(self):
        wizard = self.env["earlydryer.price.check.wizard"].create(
            {
                "branch_id": self.branch_1.id,
                "channel": "walk_in",
                "category_id": self.cat_shirt.id,
                "service_type_id": self.svc_wi.id,
                "surcharge_ids": [(6, 0, self.sur_beads.ids)],
                "express": True,
            }
        )
        self.assertEqual(wizard.product_id, self.shirt_wi)
        self.assertEqual(wizard.total, 2000)
        self.assertTrue(wizard.promised_datetime)
        self.assertIn("T Beads", wizard.breakdown)
        wizard.service_type_id = self.svc_rug
        self.assertTrue(wizard.error)
