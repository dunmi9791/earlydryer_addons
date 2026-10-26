# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CatalogCommon

ROLES_BELOW_MANAGEMENT = (
    "earlydryer_base.group_front_desk",
    "earlydryer_base.group_production",
    "earlydryer_base.group_qc",
    "earlydryer_base.group_rider",
    "earlydryer_base.group_customer_service",
    "earlydryer_base.group_branch_manager",
    "earlydryer_base.group_operations_manager",
    "earlydryer_base.group_finance",
    "earlydryer_base.group_hr",
)


@tagged("post_install", "-at_install")
class TestSecurity(CatalogCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.front_desk = cls._new_user(
            "ed_c_frontdesk", "earlydryer_base.group_front_desk", cls.branch_1
        )
        cls.branch_manager = cls._new_user(
            "ed_c_branchmgr", "earlydryer_base.group_branch_manager", cls.branch_1
        )
        cls.management = cls._new_user("ed_c_mgmt", "earlydryer_base.group_management")
        cls.item = cls.pl_walk_in_b1.item_ids[0]

    def test_front_desk_reads_but_cannot_change_prices(self):
        item = self.item.with_user(self.front_desk)
        self.assertTrue(item.fixed_price)
        self.assertTrue(self.sur_beads.with_user(self.front_desk).name)
        with self.assertRaises(AccessError):
            item.write({"fixed_price": 1})
        with self.assertRaises(AccessError):
            self.sur_beads.with_user(self.front_desk).write({"percent": 5})
        with self.assertRaises(AccessError):
            self.Surcharge.with_user(self.front_desk).create(
                {"name": "FD", "code": "FD", "compute_mode": "fixed"}
            )
        with self.assertRaises(AccessError):
            self.shirt_wi.product_tmpl_id.with_user(self.front_desk).write(
                {"list_price": 1}
            )
        with self.assertRaises(AccessError):
            self.svc_wi.with_user(self.front_desk).write(
                {"standard_turnaround_hours": 1}
            )

    def test_branch_manager_cannot_change_earlydryer_prices(self):
        # Branch Manager implies point_of_sale.group_pos_manager, which has
        # full access to product.pricelist: the record rules block it on
        # Earlydryer price lists.
        with self.assertRaises(AccessError):
            self.pl_walk_in_b1.with_user(self.branch_manager).write({"name": "Hacked"})
        with self.assertRaises(AccessError):
            self.item.with_user(self.branch_manager).write({"fixed_price": 1})

    def test_management_manages_prices(self):
        self.item.with_user(self.management).write({"fixed_price": 1234})
        self.assertEqual(self.item.fixed_price, 1234)
        self.sur_beads.with_user(self.management).write({"amount": 450})
        self.assertEqual(self.sur_beads.product_id.list_price, 450)
        surcharge = self.Surcharge.with_user(self.management).create(
            {"name": "M", "code": "MGT", "compute_mode": "fixed", "amount": 10}
        )
        self.assertEqual(surcharge.product_id.earlydryer_kind, "surcharge")
        self.pl_walk_in_b1.with_user(self.management).write({"name": "Renamed"})
        self.svc_wi.with_user(self.management).write({"standard_turnaround_hours": 20})
        self.Catalog.with_user(self.management)._generate_laundry_products(
            self.cat_shirt, self.Service.create({"name": "M svc", "code": "MSVC"})
        )

    def test_roles_do_not_imply_price_manager_groups(self):
        forbidden = self.env.ref("sales_team.group_sale_manager") | self.env.ref(
            "product.group_product_manager"
        )
        for xmlid in ROLES_BELOW_MANAGEMENT:
            group = self.env.ref(xmlid)
            self.assertFalse(
                (group | group.all_implied_ids) & forbidden,
                f"{xmlid} implies a price manager group",
            )

    def test_pricelist_feature_enabled(self):
        self.assertIn(
            self.env.ref("product.group_product_pricelist"),
            self.env.ref("base.group_user").all_implied_ids,
        )

    def test_auditlog_rules_confirmed(self):
        for xmlid in (
            "earlydryer_service_catalog.auditlog_rule_product_pricelist_item",
            "earlydryer_service_catalog.auditlog_rule_earlydryer_surcharge",
            "earlydryer_service_catalog.auditlog_rule_earlydryer_service_type",
        ):
            self.assertEqual(self.env.ref(xmlid).state, "confirmed")
