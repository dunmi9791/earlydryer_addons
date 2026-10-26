# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import WalletCommon


@tagged("post_install", "-at_install")
class TestSpend(WalletCommon):
    def test_spend_on_invoice_reconciles(self):
        self._topup(5000)
        invoice = self._invoice(8000)
        self.assertTrue(invoice.earlydryer_wallet_can_pay)
        wizard = self.env["earlydryer.wallet.spend.wizard"].create(
            {"invoice_id": invoice.id}
        )
        # the smaller of the residual and the balance
        self.assertEqual(wizard.amount, 5000)
        wizard.action_confirm()
        tx = invoice.earlydryer_wallet_transaction_ids
        self.assertEqual(tx.type, "spend")
        self.assertEqual(tx.state, "posted")
        self.assertEqual(invoice.amount_residual, 3000)
        self.assertEqual(self._balance(), 0)
        advances = tx.move_id.line_ids.filtered(
            lambda line: line.account_id == self.advances
        )
        self.assertEqual(advances.debit, 5000)
        self.assertEqual(advances.partner_id, self.customer)
        receivable = tx._earlydryer_receivable_credit()
        self.assertTrue(receivable.reconciled)
        self.assertEqual(self._gl_delta(), 0)
        self.assertFalse(invoice.earlydryer_wallet_can_pay)

    def test_spend_capped_at_balance(self):
        self._topup(1000)
        invoice = self._invoice(5000)
        with self.assertRaisesRegex(UserError, "holds"):
            invoice._earlydryer_wallet_spend(1500)
        self.assertEqual(invoice.amount_residual, 5000)
        self.assertEqual(self._balance(), 1000)

    def test_spend_capped_at_residual(self):
        self._topup(9000)
        invoice = self._invoice(2000)
        with self.assertRaisesRegex(UserError, "left to pay"):
            invoice._earlydryer_wallet_spend(3000)

    def test_spend_refused_on_blocked_wallet(self):
        self._topup(5000)
        invoice = self._invoice(2000)
        self._wallet().action_block()
        with self.assertRaisesRegex(UserError, "blocked"):
            invoice._earlydryer_wallet_spend(1000)

    def test_concurrent_spends_cannot_overdraw(self):
        """Two tills spending at once: the second posting finds the balance
        already spent (the posting locks the wallet row and reads the posted
        balance from the database, see _earlydryer_lock)."""
        self._topup(5000)
        first = self._invoice(4000)
        second = self._invoice(4000)
        first._earlydryer_wallet_spend(4000)
        with self.assertRaisesRegex(UserError, "holds"):
            second._earlydryer_wallet_spend(4000)
        self.assertEqual(self._balance(), 1000)
        self.assertEqual(second.amount_residual, 4000)
