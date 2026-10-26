# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import AccountingCommon

HEADER = (
    "account_code,account_name,debit,credit,partner_ref,plant_code,label,"
    "date_maturity\n"
)


@tagged("post_install", "-at_install")
class TestOpeningBalance(AccountingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env["account.account"]
        cls.customer = cls.env["res.partner"].create(
            {"name": "T Opening Customer", "phone": "0803 123 4567"}
        )
        cls.supplier = cls.env["res.partner"].create(
            {"name": "T Opening Supplier", "ref": "SUP-01"}
        )
        cls.receivable = cls.customer.property_account_receivable_id
        cls.payable = cls.supplier.property_account_payable_id
        cls.cash = cls.branch_1.earlydryer_cash_account_id
        cls.equity = Account.search(
            [
                *Account._check_company_domain(cls.company),
                ("account_type", "=", "equity"),
            ],
            limit=1,
        )
        cls.cutover = date(cls.today.year, 1, 1)

    def _wizard(self, rows, user=None):
        content = HEADER + "\n".join(rows) + "\n"
        return (
            self.env["earlydryer.opening.balance.wizard"]
            .with_user(user or self.user_finance)
            .create(
                {
                    "date": self.cutover,
                    "file": base64.b64encode(content.encode()),
                    "filename": "tb.csv",
                }
            )
        )

    def _good_rows(self):
        return [
            f"{self.cash.code},{self.cash.name},50000,,,{self.branch_1.code},Till,",
            (
                f"{self.receivable.code},Receivable,30000,,+2348031234567,,"
                "Old invoices,2026-02-28"
            ),
            f"{self.payable.code},Payable,,20000,SUP-01,,Old bill,2026-03-15",
            f"{self.equity.code},Equity,,60000,,,Capital,",
        ]

    def test_dry_run_catches_errors(self):
        moves = self.Move.search_count([])
        rows = [
            f"{self.cash.code},,1000,,,,,",  # unbalanced alone
            "ZZ999,Unknown,,10,,,,",
            f"{self.receivable.code},,500,,Nobody Known,,,",
            f"{self.company.earlydryer_wallet_account_id.code},Advances,,700,,,,",
        ]
        wizard = self._wizard(rows)
        wizard.action_preview()
        self.assertEqual(self.Move.search_count([]), moves)
        statuses = wizard.line_ids.sorted("row").mapped("status")
        self.assertEqual(statuses, ["ok", "account", "partner", "advances"])
        self.assertAlmostEqual(wizard.advances_tb_amount, 700.0)
        self.assertTrue(wizard.difference)
        with self.assertRaises(UserError):
            wizard.action_import()
        self.assertEqual(self.Move.search_count([]), moves)

    def test_unbalanced_needs_confirmation(self):
        rows = self._good_rows()[:-1]  # without equity: 60000 out
        wizard = self._wizard(rows)
        wizard.action_preview()
        self.assertFalse(wizard.error_count)
        self.assertAlmostEqual(wizard.difference, 60000.0)
        with self.assertRaises(UserError):
            wizard.action_import()
        wizard.confirm_difference = True
        wizard.action_import()
        equity = self.company.earlydryer_opening_equity_account_id
        line = wizard.move_id.line_ids.filtered(lambda l: l.account_id == equity)
        self.assertAlmostEqual(line.balance, -60000.0)

    def test_import_and_rerun_refused(self):
        wizard = self._wizard(self._good_rows())
        wizard.action_preview()
        self.assertFalse(wizard.error_count)
        self.assertFalse(wizard.difference)
        wizard.action_import()
        move = wizard.move_id
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.journal_id, self.company.earlydryer_opening_journal_id)
        self.assertEqual(move.date, self.cutover)
        self.assertEqual(len(move.line_ids), 4)
        receivable = move.line_ids.filtered(lambda l: l.account_id == self.receivable)
        self.assertEqual(receivable.partner_id, self.customer)
        self.assertEqual(str(receivable.date_maturity), "2026-02-28")
        payable = move.line_ids.filtered(lambda l: l.account_id == self.payable)
        self.assertEqual(payable.partner_id, self.supplier)
        cash = move.line_ids.filtered(lambda l: l.account_id == self.cash)
        self.assertEqual(
            set(cash.analytic_distribution), {str(self.branch_1.analytic_account_id.id)}
        )
        again = self._wizard(self._good_rows())
        again.action_preview()
        with self.assertRaises(UserError):
            again.action_import()
        # reversed: allowed again
        move._reverse_moves([{"date": self.cutover}], cancel=True)
        again.action_import()
        self.assertEqual(again.move_id.state, "posted")

    def test_rights(self):
        with self.assertRaises(AccessError):
            self._wizard(self._good_rows(), user=self.user_branch_manager)
