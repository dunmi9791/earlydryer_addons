# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import EarlydryerCommon


@tagged("post_install", "-at_install")
class TestBranch(EarlydryerCommon):
    def test_code_upper_case(self):
        self.assertEqual(self.branch_1.code, "TP1")
        self.branch_1.code = " wu1 "
        self.assertEqual(self.branch_1.code, "WU1")
        self.assertEqual(self.branch_1.display_name, "WU1 - Test Plant 1")

    def test_code_unique_per_company(self):
        with (
            mute_logger("odoo.sql_db"),
            self.assertRaises(IntegrityError),
            self.env.cr.savepoint(),
        ):
            self.Branch.create({"name": "Duplicate", "code": "tp1"})
        other_company = self.env["res.company"].create({"name": "Other Co"})
        vals = {"name": "Other", "code": "TP1", "company_id": other_company.id}
        if "tag_prefix" in self.Branch._fields:
            # earlydryer_tagging: tag prefixes (default: the code) are unique
            # across companies
            vals["tag_prefix"] = "OTP1"
        branch = self.Branch.create(vals)
        self.assertEqual(branch.code, "TP1")

    def test_name_search_code(self):
        found = self.Branch.name_search("TP2")
        self.assertIn(self.branch_2.id, [res[0] for res in found])

    def test_unique_warehouse(self):
        warehouse = self.env["stock.warehouse"].create(
            {"name": "WH T1", "code": "WHT1"}
        )
        self.branch_1.warehouse_id = warehouse
        self.assertEqual(warehouse.earlydryer_branch_id, self.branch_1)
        with self.assertRaises(ValidationError):
            self.branch_2.warehouse_id = warehouse

    def test_unique_cash_journal(self):
        journal = self.env["account.journal"].create(
            {"name": "Cash T1", "code": "CST1", "type": "cash"}
        )
        self.branch_1.cash_journal_id = journal
        with self.assertRaises(ValidationError):
            self.branch_2.cash_journal_id = journal

    def test_unique_analytic_account(self):
        plan = self.env["account.analytic.plan"].create({"name": "Test plants"})
        account = self.env["account.analytic.account"].create(
            {"name": "Plant T1", "plan_id": plan.id}
        )
        self.branch_1.analytic_account_id = account
        with self.assertRaises(ValidationError):
            self.branch_2.analytic_account_id = account

    def test_generate_shelves_padding_and_skip(self):
        self.assertEqual(
            self.branch_1.shelf_ids.mapped("name"), ["A-01", "A-02", "A-03"]
        )
        # archived shelves count as existing too
        self.branch_1.shelf_ids.filtered(lambda s: s.name == "A-02").active = False
        wizard = self.env["earlydryer.branch.shelf.generate"].create(
            {
                "branch_id": self.branch_1.id,
                "prefix": "A",
                "start": 1,
                "count": 5,
                "padding": 3,
            }
        )
        self.assertEqual(wizard.preview, "A-001 … A-005")
        wizard.action_generate()
        created = self.branch_1._generate_shelves("A", 1, 5, 2)
        self.assertEqual(created.mapped("name"), ["A-04", "A-05"])
        names = (
            self.Shelf.with_context(active_test=False)
            .search([("branch_id", "=", self.branch_1.id)])
            .mapped("name")
        )
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("A-001", names)
        # 2 active A-xx + 5 A-00x + A-04, A-05
        self.assertEqual(self.branch_1.shelf_count, 9)

    def test_shelf_name_unique_per_branch(self):
        with (
            mute_logger("odoo.sql_db"),
            self.assertRaises(IntegrityError),
            self.env.cr.savepoint(),
        ):
            self.Shelf.create({"branch_id": self.branch_1.id, "name": "A-01"})
        self.Shelf.create({"branch_id": self.branch_2.id, "name": "A-01"})

    def test_archive_branch_archives_shelves(self):
        self.branch_2.action_archive()
        self.assertFalse(
            self.Shelf.search([("branch_id", "=", self.branch_2.id)]),
        )
        self.assertTrue(self.branch_1.shelf_ids)

    def test_default_branch_in_allowed(self):
        user = self._new_user(
            "ed_t_default", "earlydryer_base.group_front_desk", self.branch_1
        )
        self.assertEqual(user.earlydryer_branch_id, self.branch_1)
        with self.assertRaises(ValidationError):
            user.earlydryer_branch_id = self.branch_2
        # user switches default branch from preferences (self write)
        user.earlydryer_branch_ids = [(4, self.branch_2.id)]
        user.with_user(user).write({"earlydryer_branch_id": self.branch_2.id})
        self.assertEqual(user.earlydryer_branch_id, self.branch_2)

    def test_branch_mixin_default(self):
        user = self._new_user(
            "ed_t_mixin", "earlydryer_base.group_front_desk", self.branch_2
        )
        Mixin = self.env["earlydryer.branch.mixin"].with_user(user)
        self.assertEqual(Mixin._default_earlydryer_branch_id(), self.branch_2)
        self.assertEqual(
            Mixin._earlydryer_branch_domain(),
            Domain("earlydryer_branch_id", "in", [self.branch_2.id]),
        )
