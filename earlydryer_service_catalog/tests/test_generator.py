# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from .common import CatalogCommon


@tagged("post_install", "-at_install")
class TestGenerator(CatalogCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cat_a = cls.Category.create({"name": "Gen A", "code": "GENA"})
        cls.cat_b = cls.Category.create({"name": "Gen B", "code": "GENB"})
        cls.svc_any = cls.Service.create({"name": "Gen Any", "code": "GANY"})
        cls.svc_b_only = cls.Service.create(
            {
                "name": "Gen B only",
                "code": "GBON",
                "allowed_category_ids": [Command.set(cls.cat_b.ids)],
            }
        )
        cls.categories = cls.cat_a | cls.cat_b
        cls.services = cls.svc_any | cls.svc_b_only

    def _laundry(self):
        return self.env["product.template"].search(
            [
                ("earlydryer_kind", "=", "laundry"),
                ("earlydryer_garment_category_id", "in", self.categories.ids),
            ]
        )

    def test_generates_allowed_combinations(self):
        tax = self.env["account.tax"].create(
            {"name": "T VAT 7.5", "amount": 7.5, "type_tax_use": "sale"}
        )
        wizard = self.env["earlydryer.catalog.generate.wizard"].create(
            {
                "category_ids": [Command.set(self.categories.ids)],
                "service_type_ids": [Command.set(self.services.ids)],
                "list_price": 250,
                "tax_ids": [Command.set(tax.ids)],
            }
        )
        self.assertEqual(wizard.combination_count, 3)
        action = wizard.action_generate()
        self.assertIn(
            "3 products created, 0 existing skipped", action["params"]["message"]
        )
        products = self._laundry()
        combos = {
            (p.earlydryer_garment_category_id, p.earlydryer_service_type_id)
            for p in products
        }
        self.assertEqual(
            combos,
            {
                (self.cat_a, self.svc_any),
                (self.cat_b, self.svc_any),
                (self.cat_b, self.svc_b_only),
            },
        )
        product = products.filtered(
            lambda p: p.earlydryer_garment_category_id == self.cat_a
        )
        self.assertEqual(product.name, "Gen A - Gen Any")
        self.assertEqual(product.default_code, "GENA-GANY")
        self.assertEqual(product.type, "service")
        self.assertTrue(product.sale_ok)
        self.assertFalse(product.purchase_ok)
        self.assertTrue(product.available_in_pos)
        self.assertEqual(product.invoice_policy, "order")
        self.assertEqual(product.list_price, 250)
        self.assertEqual(product.taxes_id, tax)
        self.assertTrue(self.svc_any.pos_category_id)
        self.assertEqual(product.pos_categ_ids, self.svc_any.pos_category_id)

    def test_default_without_tax(self):
        created, _skipped = self.Catalog._generate_laundry_products(
            self.cat_a, self.svc_any
        )
        self.assertFalse(created.taxes_id)

    def test_idempotent(self):
        created, skipped = self.Catalog._generate_laundry_products(
            self.categories, self.services
        )
        self.assertEqual((len(created), skipped), (3, 0))
        created[0].write({"list_price": 999, "name": "Renamed"})
        created[1].action_archive()
        again, skipped = self.Catalog._generate_laundry_products(
            self.categories, self.services
        )
        self.assertFalse(again)
        self.assertEqual(skipped, 3)
        self.assertEqual(created[0].name, "Renamed")
        self.assertEqual(created[0].list_price, 999)
        self.assertEqual(len(self._laundry()), 2)

    def test_turnaround_from_service_and_override(self):
        product = self.shirt_wi.product_tmpl_id
        self.assertEqual(product.earlydryer_turnaround_hours, 16)
        self.assertEqual(product.earlydryer_express_turnaround_hours, 4)
        product.earlydryer_turnaround_hours_override = 10
        self.assertEqual(product.earlydryer_turnaround_hours, 10)
        self.svc_wi.express_turnaround_hours = 3
        self.assertEqual(product.earlydryer_express_turnaround_hours, 3)
        self.assertEqual(self.rug_rug.earlydryer_express_turnaround_hours, 0)

    def test_get_laundry_product_missing(self):
        with self.assertRaises(UserError):
            self.Catalog.get_laundry_product(self.cat_shirt, self.svc_rug)
