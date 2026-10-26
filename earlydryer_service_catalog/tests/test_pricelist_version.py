# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CatalogCommon


@tagged("post_install", "-at_install")
class TestPricelistVersion(CatalogCommon):
    def _wizard(self, days=10, **vals):
        return self.env["earlydryer.pricelist.version.wizard"].create(
            {
                "pricelist_id": self.pl_walk_in_b1.id,
                "effective_date": fields.Date.context_today(self.env.user)
                + timedelta(days=days),
                **vals,
            }
        )

    def _price_on(self, product, when):
        return self.Catalog.price_item(
            product, False, self.branch_1, "walk_in", date=when
        )["unit_price"]

    def test_new_version(self):
        old_items = self.pl_walk_in_b1.item_ids
        wizard = self._wizard(percent_change=12, rounding=50)
        self.assertEqual(wizard.item_count, 3)
        start = wizard._effective_datetime()
        before = fields.Datetime.now()
        wizard.action_create_version()

        new_items = self.pl_walk_in_b1.item_ids - old_items
        self.assertEqual(len(new_items), 3)
        self.assertEqual(set(new_items.mapped("date_start")), {start})
        self.assertEqual(
            set(old_items.mapped("date_end")), {start - timedelta(seconds=1)}
        )
        # 1000 * 1.12 = 1120 -> nearest 50 = 1100; 2000 * 1.12 = 2240 -> 2250
        self.assertEqual(
            sorted(new_items.mapped("fixed_price")), [550.0, 1100.0, 2250.0]
        )
        # prices before the effective date are unchanged, after it they change
        self.assertEqual(self._price_on(self.shirt_wi, before), 1000)
        self.assertEqual(
            self._price_on(self.shirt_wi, start - timedelta(hours=1)), 1000
        )
        self.assertEqual(self._price_on(self.shirt_wi, start), 1100)
        self.assertEqual(
            self._price_on(self.shirt_dc, start + timedelta(days=30)), 2250
        )

    def test_second_version_chains(self):
        self._wizard(days=10, percent_change=10).action_create_version()
        later = self._wizard(days=40, percent_change=10)
        self.assertEqual(later.item_count, 3)
        later.action_create_version()
        self.assertEqual(
            self._price_on(self.shirt_wi, later._effective_datetime()), 1210
        )
        # cannot insert a version before an existing future one
        with self.assertRaises(UserError):
            self._wizard(days=20).action_create_version()

    def test_effective_date_must_be_future(self):
        with self.assertRaises(UserError):
            self._wizard(days=0).action_create_version()
        with self.assertRaises(UserError):
            self._wizard(days=-30).action_create_version()
        self.assertFalse(self.pl_walk_in_b1.item_ids.filtered("date_end"))
