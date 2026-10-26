# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import AccountingCommon


@tagged("post_install", "-at_install")
class TestCash(AccountingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rider = cls.env["hr.employee"].create({"name": "T Rider"})

    def _cash_day(self, amount=5000.0):
        order = self._sync(self._payload([self._line(self.shirt_wi, price=amount)]))
        self._close_session(order.session_id)
        return order.session_id

    def _lodgement(self, user, amount=None, branch=None):
        vals = {
            "branch_id": (branch or self.branch_1).id,
            "bank_journal_id": self.bank_journal.id,
            "reference": "T-SLIP",
        }
        wizard = (
            self.env["earlydryer.cash.lodgement.wizard"].with_user(user).create(vals)
        )
        if amount is not None:
            wizard.amount = amount
        return wizard

    def test_lodgement_posts_cash_to_transit(self):
        self._cash_day(5000.0)
        wizard = self._lodgement(self.user_branch_manager)
        self.assertAlmostEqual(wizard.cash_balance, 5000.0)
        self.assertAlmostEqual(wizard.amount, 4000.0)  # float 1000 kept
        self.assertFalse(wizard.below_float)
        move = wizard._earlydryer_lodge()
        transit = self.company.earlydryer_cash_transit_account_id
        cash = self.branch_1.earlydryer_cash_account_id
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.earlydryer_kind, "lodgement")
        self.assertAlmostEqual(
            move.line_ids.filtered(lambda l: l.account_id == transit).balance, 4000.0
        )
        self.assertAlmostEqual(
            move.line_ids.filtered(lambda l: l.account_id == cash).balance, -4000.0
        )
        self.assertAlmostEqual(
            self.branch_1._earlydryer_cash_balance(self.today), 1000.0
        )

    def test_lodgement_below_float_rights(self):
        self._cash_day(5000.0)
        with self.assertRaises(AccessError):
            self._lodgement(self.user_front_desk, amount=5000.0)._earlydryer_lodge()
        with self.assertRaises(AccessError):
            self._lodgement(self.user_front_desk, amount=1000.0)._earlydryer_lodge()
        finance = self._lodgement(self.user_finance, amount=5000.0)
        self.assertTrue(finance.below_float)
        with self.assertRaises(AccessError):
            finance._earlydryer_lodge()
        move = self._lodgement(
            self.user_branch_manager, amount=5000.0
        )._earlydryer_lodge()
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(self.branch_1._earlydryer_cash_balance(self.today), 0.0)

    def test_branch_manager_lodges_own_plant_only(self):
        with self.assertRaises(AccessError):
            self._lodgement(
                self.user_branch_manager, amount=10.0, branch=self.branch_2
            )._earlydryer_lodge()

    def test_rider_handover(self):
        move = self.Move.with_user(self.user_branch_manager)._earlydryer_rider_handover(
            self.branch_1, 2500.0, self.rider
        )
        rider_account = self.branch_1.earlydryer_rider_account_id
        cash = self.branch_1.earlydryer_cash_account_id
        self.assertEqual(move.earlydryer_kind, "rider_handover")
        self.assertEqual(move.earlydryer_rider_employee_id, self.rider)
        self.assertAlmostEqual(
            move.line_ids.filtered(lambda l: l.account_id == cash).balance, 2500.0
        )
        self.assertAlmostEqual(
            move.line_ids.filtered(lambda l: l.account_id == rider_account).balance,
            -2500.0,
        )
        with self.assertRaises(AccessError):
            self.Move.with_user(self.user_front_desk)._earlydryer_rider_handover(
                self.branch_1, 10.0, self.rider
            )
        wizard = self.env["earlydryer.rider.handover.wizard"].create(
            {"branch_id": self.branch_1.id, "rider_id": self.rider.id, "amount": 100.0}
        )
        self.assertEqual(wizard.action_handover()["res_model"], "account.move")

    def test_daily_cash_report_matches_entries(self):
        self._cash_day(6000.0)
        self.Move._earlydryer_rider_handover(self.branch_1, 2000.0, self.rider)
        self._lodgement(self.env.user, amount=3000.0)._earlydryer_lodge()
        report = self.env["report.earlydryer_accounting_ng.report_daily_cash"]
        data = report.with_user(self.user_front_desk)._earlydryer_daily_cash_data(
            self.branch_1, self.today
        )
        lines = self.MoveLine.search(
            [
                ("account_id", "=", self.branch_1.earlydryer_cash_account_id.id),
                ("parent_state", "=", "posted"),
                ("date", "=", self.today),
            ]
        )
        self.assertAlmostEqual(data["pos_cash"], 6000.0)
        self.assertAlmostEqual(data["rider_handovers"], 2000.0)
        self.assertAlmostEqual(data["lodgements"], -3000.0)
        self.assertAlmostEqual(
            data["closing"] - data["opening"], sum(lines.mapped("balance"))
        )
        self.assertAlmostEqual(
            data["closing"], self.branch_1._earlydryer_cash_balance(self.today)
        )
        self.assertEqual(data["float"], 1000.0)
        # non-cash takings by method, with order counts
        account = self._sync(
            self._payload(
                [self._line(self.shirt_wi, price=700.0)], paid=0.0, account=700.0
            )
        )
        self._close_session(account.session_id)
        data = report._earlydryer_daily_cash_data(self.branch_1, self.today)
        methods = {row["method"]: row for row in data["non_cash"]}
        self.assertAlmostEqual(methods[self.pm_account]["amount"], 700.0)
        self.assertEqual(methods[self.pm_account]["orders"], 1)
        # another plant's report is refused to a Front Desk of plant 1
        with self.assertRaises(AccessError):
            report.with_user(self.user_front_desk)._earlydryer_daily_cash_data(
                self.branch_2, self.today
            )
        # Finance has no Point of Sale rights: the report reads the POS
        # payments itself, after its plant check
        self.env["ir.actions.report"].with_user(self.user_finance)._render_qweb_pdf(
            "earlydryer_accounting_ng.action_report_daily_cash",
            self.branch_1.ids,
            data={"date": str(self.today)},
        )
