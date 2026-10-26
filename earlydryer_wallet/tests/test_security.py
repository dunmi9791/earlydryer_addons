# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import WalletCommon


@tagged("post_install", "-at_install")
class TestSecurity(WalletCommon):
    def test_customer_service_cannot_top_up(self):
        with self.assertRaises(AccessError):
            self._topup(1000, user=self.user_cs)

    def test_front_desk_tops_up_own_cash_only(self):
        tx = self._topup(1000, user=self.user_front_desk)
        self.assertEqual(tx.state, "posted")
        with self.assertRaises(AccessError):
            self._topup(1000, journal=self.bank, user=self.user_front_desk)
        # a Branch Manager uses any journal
        self.assertEqual(
            self._topup(1000, journal=self.bank, user=self.user_manager).state, "posted"
        )

    def test_front_desk_cannot_reverse_or_import(self):
        tx = self._topup(1000)
        with self.assertRaises(AccessError):
            tx.with_user(self.user_front_desk).action_open_reverse_wizard()
        with self.assertRaises(AccessError):
            self.env["earlydryer.wallet.import.wizard"].with_user(
                self.user_front_desk
            ).create({"file": b"", "filename": "x.csv"}).action_preview()

    def test_front_desk_cannot_credit(self):
        with self.assertRaises(AccessError):
            self.env["earlydryer.wallet.credit.wizard"].with_user(
                self.user_front_desk
            ).create(
                {"partner_id": self.customer.id, "amount": 100, "reason": "x"}
            ).action_confirm()

    def test_direct_writes_refused(self):
        tx = self._topup(1000)
        wallet = self._wallet()
        for user in (self.user_front_desk, self.user_finance, self.user_management):
            # visible to every internal user
            self.assertEqual(wallet.with_user(user).balance, 1000)
            self.assertEqual(tx.with_user(user).amount, 1000)
            with self.assertRaises(AccessError):
                tx.with_user(user).write({"reference": "x"})
            with self.assertRaises(AccessError):
                wallet.with_user(user).write({"state": "blocked"})
            with self.assertRaises(AccessError):
                self.Tx.with_user(user).create(
                    {
                        "wallet_id": wallet.id,
                        "type": "credit",
                        "amount": 5,
                        "reason": "x",
                    }
                )

    def test_control_report_finance_only(self):
        with self.assertRaises(AccessError):
            self.env["earlydryer.wallet.control"].with_user(self.user_manager).create(
                {}
            )
        report = self._control(user=self.user_finance)
        self.assertEqual(report.difference, 0)

    def test_block_finance_only(self):
        self._topup(1000)
        wallet = self._wallet()
        with self.assertRaises(AccessError):
            wallet.with_user(self.user_manager).action_block()
        wallet.with_user(self.user_finance).action_block()
        self.assertEqual(wallet.state, "blocked")
