# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import CatalogCommon


@tagged("post_install", "-at_install")
class TestConstraints(CatalogCommon):
    def _laundry_vals(self, category, service):
        return {
            "name": "Duplicate",
            "type": "service",
            "earlydryer_kind": "laundry",
            "earlydryer_garment_category_id": category.id,
            "earlydryer_service_type_id": service.id,
        }

    def test_codes_upper_case(self):
        self.assertEqual(self.cat_shirt.code, "TSHIRT")
        self.cat_shirt.code = " tshirt2 "
        self.assertEqual(self.cat_shirt.code, "TSHIRT2")

    def test_laundry_product_unique(self):
        with (
            mute_logger("odoo.sql_db"),
            self.assertRaises(IntegrityError),
            self.env.cr.savepoint(),
        ):
            self.env["product.template"].create(
                self._laundry_vals(self.cat_shirt, self.svc_wi)
            )
        # archived products do not count
        self.shirt_wi.product_tmpl_id.action_archive()
        self.env.flush_all()  # the unique index is checked by PostgreSQL
        new = self.env["product.template"].create(
            self._laundry_vals(self.cat_shirt, self.svc_wi)
        )
        self.assertTrue(new)

    def test_laundry_needs_category_and_service(self):
        with self.assertRaises(ValidationError):
            self.env["product.template"].create(
                {"name": "X", "type": "service", "earlydryer_kind": "laundry"}
            )

    def test_pricelist_branch_channel_unique(self):
        with (
            mute_logger("odoo.sql_db"),
            self.assertRaises(IntegrityError),
            self.env.cr.savepoint(),
        ):
            self.Pricelist.create(
                {
                    "name": "Duplicate",
                    "earlydryer_channel": "walk_in",
                    "earlydryer_branch_id": self.branch_1.id,
                }
            )
        # other channel, other branch, contract lists and archived lists are fine
        self.Pricelist.create(
            {
                "name": "B1 pickup",
                "earlydryer_channel": "pickup",
                "earlydryer_branch_id": self.branch_1.id,
            }
        )
        self.Pricelist.create(
            {
                "name": "B2 walk-in",
                "earlydryer_channel": "walk_in",
                "earlydryer_branch_id": self.branch_2.id,
            }
        )
        for name in ("Contract 1", "Contract 2"):
            self.Pricelist.create(
                {
                    "name": name,
                    "earlydryer_channel": "corporate",
                    "earlydryer_is_contract": True,
                    "earlydryer_branch_id": self.branch_1.id,
                }
            )
        self.pl_walk_in_b1.action_archive()
        self.env.flush_all()
        self.Pricelist.create(
            {
                "name": "New B1 walk-in",
                "earlydryer_channel": "walk_in",
                "earlydryer_branch_id": self.branch_1.id,
            }
        )

    def test_contract_must_be_corporate(self):
        with self.assertRaises(ValidationError):
            self.Pricelist.create(
                {
                    "name": "Bad contract",
                    "earlydryer_channel": "walk_in",
                    "earlydryer_is_contract": True,
                }
            )

    def test_express_shorter_than_standard(self):
        with self.assertRaises(ValidationError):
            self.svc_wi.express_turnaround_hours = 16
        with self.assertRaises(ValidationError):
            self.svc_rug.express_available = True

    def test_surcharge_product_created(self):
        product = self.sur_beads.product_id
        self.assertEqual(product.earlydryer_kind, "surcharge")
        self.assertEqual(product.default_code, "SUR-TBEAD")
        self.assertEqual(product.list_price, 300)
        self.assertEqual(product.type, "service")
        self.assertTrue(product.available_in_pos)
        self.assertFalse(product.taxes_id)
        with self.assertRaises(ValidationError):
            self.Surcharge.create(
                {"name": "Bad", "code": "BAD", "compute_mode": "percent", "percent": 0}
            )
