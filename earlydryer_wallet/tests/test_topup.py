# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import WalletCommon


@tagged("post_install", "-at_install")
class TestTopup(WalletCommon):
    def test_setup_accounts(self):
        self.assertEqual(self.advances.account_type, "liability_current")
        self.assertTrue(self.advances.reconcile)
        self.assertEqual(self.company.earlydryer_wallet_journal_id.type, "general")
        self.assertTrue(self.pm_wallet)
        self.assertFalse(self.pm_wallet.journal_id)
        self.assertTrue(self.pm_wallet.split_transactions)
        self.assertEqual(self.pm_wallet.type, "pay_later")
        # the Customer Account check of earlydryer_pos ignores the wallet
        self.assertNotIn(self.pm_wallet, self.config._earlydryer_account_methods())
        # setup is idempotent
        self.company._earlydryer_wallet_setup()
        self.assertEqual(self.company.earlydryer_wallet_account_id, self.advances)

    def test_topup_cash_entry_and_balance(self):
        tx = self._topup(5000)
        self.assertEqual(tx.state, "posted")
        self.assertEqual(tx.signed_amount, 5000)
        self.assertTrue(tx.payment_id)
        lines = tx.move_id.line_ids
        debit = lines.filtered(lambda line: line.debit)
        credit = lines.filtered(lambda line: line.credit)
        # cash: straight to the cash journal's account
        self.assertEqual(debit.account_id, self.journal_cash.default_account_id)
        self.assertEqual(debit.debit, 5000)
        self.assertEqual(credit.account_id, self.advances)
        self.assertEqual(credit.partner_id, self.customer)
        self.assertEqual(credit.credit, 5000)
        self.assertEqual(self._balance(), 5000)
        self.assertEqual(self._gl_delta(), 5000)

    def test_topup_bank_uses_outstanding_receipts(self):
        tx = self._topup(3000, journal=self.bank)
        debit = tx.move_id.line_ids.filtered(lambda line: line.debit)
        self.assertNotEqual(debit.account_id, self.advances)
        self.assertEqual(debit.account_id, tx.payment_id.outstanding_account_id)
        credit = tx.move_id.line_ids.filtered(lambda line: line.credit)
        self.assertEqual(credit.account_id, self.advances)

    def test_minimum_topup(self):
        self.company.earlydryer_wallet_min_topup = 1000
        with self.assertRaisesRegex(UserError, "minimum top-up"):
            self._topup(500)
        self.assertEqual(self._topup(1000).amount, 1000)

    def test_wallet_per_commercial_partner(self):
        contact = self.env["res.partner"].create(
            {"name": "T Contact", "parent_id": self.customer.id}
        )
        self._topup(2000, partner=contact)
        self.assertEqual(self._balance(self.customer), 2000)
        self.assertEqual(self.Wallet.search_count([("partner_id", "=", contact.id)]), 0)

    def test_blocked_wallet_cannot_be_topped_up(self):
        self._topup(1000)
        self._wallet().action_block()
        with self.assertRaisesRegex(UserError, "blocked"):
            self._topup(1000)

    def test_posted_transaction_is_never_edited(self):
        tx = self._topup(1000)
        with self.assertRaises(UserError):
            tx.with_context(earlydryer_wallet_write=False).sudo().write({"amount": 5})
        with self.assertRaises(UserError):
            tx.sudo().unlink()
