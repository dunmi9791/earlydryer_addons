# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import CatalogCommon


@tagged("post_install", "-at_install")
class TestPricelistResolution(CatalogCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # make the test independent of demo price lists
        cls.Pricelist.search(
            [
                ("earlydryer_channel", "in", ["pickup", "corporate"]),
                ("earlydryer_is_contract", "=", False),
            ]
        ).action_archive()
        cls.pl_pickup_all = cls.Pricelist.create(
            {"name": "T Pickup (all plants)", "earlydryer_channel": "pickup"}
        )
        cls.pl_contract = cls.Pricelist.create(
            {
                "name": "T Contract",
                "earlydryer_channel": "corporate",
                "earlydryer_is_contract": True,
            }
        )
        cls.corporate = cls.env["res.partner"].create(
            {"name": "T Corporate", "is_company": True}
        )
        cls.corporate.property_product_pricelist = cls.pl_contract
        cls.employee = cls.env["res.partner"].create(
            {"name": "T Employee", "parent_id": cls.corporate.id}
        )
        cls.walk_in_customer = cls.env["res.partner"].create({"name": "T Walk-in"})
        cls.resolve = cls.Pricelist._earlydryer_resolve_pricelist

    def test_contract_of_commercial_partner_wins(self):
        self.assertEqual(
            self.resolve(self.employee, self.branch_1, "walk_in"), self.pl_contract
        )
        self.assertEqual(
            self.resolve(self.corporate, self.branch_1, "pickup"), self.pl_contract
        )

    def test_contract_restricted_to_other_plant(self):
        self.pl_contract.earlydryer_branch_id = self.branch_2
        self.assertEqual(
            self.resolve(self.corporate, self.branch_1, "walk_in"), self.pl_walk_in_b1
        )
        self.assertEqual(
            self.resolve(self.corporate, self.branch_2, "walk_in"), self.pl_contract
        )

    def test_non_contract_partner_list_ignored(self):
        self.walk_in_customer.property_product_pricelist = self.pl_pickup_all
        self.assertEqual(
            self.resolve(self.walk_in_customer, self.branch_1, "walk_in"),
            self.pl_walk_in_b1,
        )

    def test_branch_channel(self):
        self.assertEqual(
            self.resolve(self.walk_in_customer, self.branch_1, "walk_in"),
            self.pl_walk_in_b1,
        )

    def test_channel_only(self):
        self.assertEqual(
            self.resolve(False, self.branch_1, "pickup"), self.pl_pickup_all
        )
        self.assertEqual(
            self.resolve(False, self.branch_2, "pickup"), self.pl_pickup_all
        )
        branch_pickup = self.Pricelist.create(
            {
                "name": "T Pickup B2",
                "earlydryer_channel": "pickup",
                "earlydryer_branch_id": self.branch_2.id,
            }
        )
        self.assertEqual(self.resolve(False, self.branch_2, "pickup"), branch_pickup)

    def test_company_default(self):
        default = self.Pricelist._earlydryer_company_default(self.env.company)
        self.assertTrue(default)
        self.assertFalse(default.earlydryer_channel)
        with self.assertLogs(
            "odoo.addons.earlydryer_service_catalog.models.product_pricelist",
            level="WARNING",
        ):
            self.assertEqual(self.resolve(False, self.branch_1, "corporate"), default)
