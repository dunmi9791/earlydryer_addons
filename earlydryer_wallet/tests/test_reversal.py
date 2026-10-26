# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import WalletCommon


@tagged("post_install", "-at_install")
class TestReversal(WalletCommon):
    def test_reverse_topup(self):
        tx = self._topup(4000)
        reversal = tx.with_user(self.user_finance)._earlydryer_reverse(
            "T wrong customer"
        )
        self.assertEqual(reversal.type, "reversal")
        self.assertEqual(reversal.signed_amount, -4000)
        self.assertEqual(reversal.state, "posted")
        self.assertEqual(tx.reversal_id, reversal)
        self.assertEqual(reversal.move_id.reversed_entry_id, tx.move_id)
        self.assertEqual(self._balance(), 0)
        self.assertEqual(self._gl_delta(), 0)
        with self.assertRaises(UserError):
            tx.with_user(self.user_finance)._earlydryer_reverse("again")

    def test_reverse_spend_reopens_invoice(self):
        self._topup(4000)
        invoice = self._invoice(4000)
        spend = invoice._earlydryer_wallet_spend(4000)
        self.assertEqual(invoice.amount_residual, 0)
        reversal = spend.with_user(self.user_finance)._earlydryer_reverse(
            "T paid twice"
        )
        self.assertEqual(reversal.signed_amount, 4000)
        self.assertEqual(invoice.amount_residual, 4000)
        self.assertEqual(self._balance(), 4000)
        self.assertEqual(self._gl_delta(), 4000)

    def test_reverse_needs_reason_and_finance(self):
        tx = self._topup(4000)
        with self.assertRaises(UserError):
            tx.with_user(self.user_finance)._earlydryer_reverse(" ")
        for user in (self.user_front_desk, self.user_manager, self.user_cs):
            with self.assertRaises(AccessError):
                tx.with_user(user)._earlydryer_reverse("T no")
        self.assertFalse(tx.reversal_id)

    def test_reverse_topup_refused_when_spent(self):
        tx = self._topup(4000)
        self._invoice(4000)._earlydryer_wallet_spend(3000)
        with self.assertRaisesRegex(UserError, "holds"):
            tx.with_user(self.user_finance)._earlydryer_reverse("T no")
