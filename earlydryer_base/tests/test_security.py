# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import EarlydryerCommon


@tagged("post_install", "-at_install")
class TestSecurity(EarlydryerCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.front_desk = cls._new_user(
            "ed_t_frontdesk", "earlydryer_base.group_front_desk", cls.branch_1
        )
        cls.finance = cls._new_user("ed_t_finance", "earlydryer_base.group_finance")
        cls.branch_manager = cls._new_user(
            "ed_t_branchmgr", "earlydryer_base.group_branch_manager", cls.branch_1
        )
        cls.management = cls._new_user("ed_t_mgmt", "earlydryer_base.group_management")
        cls.ours = cls.branch_1 | cls.branch_2

    def test_front_desk_sees_own_branch_only(self):
        branches = self.Branch.with_user(self.front_desk).search([])
        self.assertEqual(branches & self.ours, self.branch_1)
        shelves = self.Shelf.with_user(self.front_desk).search([])
        self.assertEqual(shelves.branch_id & self.ours, self.branch_1)
        with self.assertRaises(AccessError):
            self.branch_2.with_user(self.front_desk).read(["name"])

    def test_finance_sees_all_branches(self):
        branches = self.Branch.with_user(self.finance).search([])
        self.assertEqual(branches & self.ours, self.ours)
        shelves = self.Shelf.with_user(self.finance).search([])
        self.assertEqual(shelves.branch_id & self.ours, self.ours)

    def test_front_desk_cannot_write_branch(self):
        with self.assertRaises(AccessError):
            self.branch_1.with_user(self.front_desk).write({"name": "Hacked"})
        with self.assertRaises(AccessError):
            self.Branch.with_user(self.front_desk).create({"name": "X", "code": "X"})

    def test_branch_manager_edits_own_shelves_only(self):
        shelf_1 = self.branch_1.shelf_ids[0]
        shelf_1.with_user(self.branch_manager).write({"capacity": 30})
        self.assertEqual(shelf_1.capacity, 30)
        self.Shelf.with_user(self.branch_manager).create(
            {"branch_id": self.branch_1.id, "name": "Z-01"}
        )
        with self.assertRaises(AccessError):
            self.branch_2.shelf_ids[0].with_user(self.branch_manager).write(
                {"capacity": 5}
            )
        with self.assertRaises(AccessError):
            self.branch_1.with_user(self.branch_manager).write({"name": "Renamed"})

    def test_allowed_branch_change_clears_rule_cache(self):
        Branch = self.Branch.with_user(self.front_desk)
        self.assertEqual(Branch.search([]) & self.ours, self.branch_1)
        self.front_desk.earlydryer_branch_ids = [(4, self.branch_2.id)]
        self.assertEqual(Branch.search([]) & self.ours, self.ours)
        self.branch_2.user_ids = [(3, self.front_desk.id)]
        self.assertEqual(Branch.search([]) & self.ours, self.branch_1)

    def test_group_hierarchy(self):
        user = self.management
        for xmlid in (
            "earlydryer_base.group_branch_manager",
            "earlydryer_base.group_operations_manager",
            "earlydryer_base.group_finance",
            "earlydryer_base.group_hr",
            "earlydryer_base.group_all_branches",
            "earlydryer_base.group_front_desk",
            "earlydryer_base.group_qc",
            "earlydryer_base.group_production",
            "earlydryer_base.group_rider",
            "earlydryer_base.group_customer_service",
            "point_of_sale.group_pos_manager",
            "account.group_account_manager",
        ):
            self.assertTrue(user.has_group(xmlid), xmlid)
        self.assertFalse(user.has_group("earlydryer_base.group_admin"))
        self.assertFalse(user.has_group("base.group_system"))
        front_desk = self.front_desk
        self.assertTrue(front_desk.has_group("point_of_sale.group_pos_user"))
        self.assertTrue(front_desk.has_group("stock.group_stock_user"))
        self.assertFalse(front_desk.has_group("earlydryer_base.group_all_branches"))
        self.assertFalse(front_desk.has_group("point_of_sale.group_pos_manager"))

    def test_front_desk_cannot_manage_approval_rules(self):
        rule = self.env["earlydryer.approval.rule"].create(
            {
                "name": "Test",
                "approval_type": "discount",
                "model_id": self.env["ir.model"]._get_id("res.partner"),
                "approver_group_id": self.env.ref(
                    "earlydryer_base.group_branch_manager"
                ).id,
                "max_value": 5,
            }
        )
        rule.with_user(self.front_desk).read(["name"])
        with self.assertRaises(AccessError):
            rule.with_user(self.front_desk).write({"max_value": 50})
        rule.with_user(self.management).write({"max_value": 6})
