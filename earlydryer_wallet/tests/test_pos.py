# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import WalletCommon


@tagged("post_install", "-at_install")
class TestPos(WalletCommon):
    def test_wallet_payment_is_a_spend_without_move(self):
        self._topup(5000)
        price = self._price(self.shirt_wi)
        order = self._sync(
            self._wallet_payload([self._line(self.shirt_wi)], wallet=price)
        )
        tx = order.earlydryer_wallet_transaction_ids
        self.assertEqual(tx.type, "spend")
        self.assertEqual(tx.source, "pos")
        self.assertEqual(tx.state, "posted")
        self.assertFalse(tx.move_id)
        self.assertEqual(tx.employee_id, self.emp_front_desk)
        self.assertEqual(tx.earlydryer_branch_id, self.branch_1)
        self.assertEqual(tx.laundry_job_id, order.earlydryer_job_id)
        self.assertEqual(self._balance(), 5000 - price)
        # paid, not a customer-account balance
        job = order.earlydryer_job_id
        self.assertEqual(order._earlydryer_pay_later_amount(), 0)
        amounts = job._earlydryer_pos_amounts()
        self.assertEqual(amounts["paid"], amounts["total"])
        self.assertEqual(job.amount_due, 0)

    def test_topup_line_creates_topup(self):
        line = self._line(self.topup_product, price=3000)
        order = self._sync(self._wallet_payload([line]))
        tx = order.earlydryer_wallet_transaction_ids
        self.assertEqual(tx.type, "topup")
        self.assertEqual(tx.source, "pos")
        self.assertFalse(tx.move_id)
        self.assertFalse(order.earlydryer_job_id)
        self.assertEqual(self._balance(), 3000)

    def test_offline_overdraw_is_recorded_and_flagged(self):
        self._topup(100)
        price = self._price(self.shirt_wi)
        self.assertGreater(price, 100)
        order = self._sync(
            self._wallet_payload([self._line(self.shirt_wi)], wallet=price)
        )
        tx = order.earlydryer_wallet_transaction_ids
        self.assertEqual(tx.state, "posted")
        self.assertTrue(tx.overdrawn)
        self.assertEqual(tx.shortfall, price - 100)
        wallet = self._wallet()
        self.assertTrue(wallet.overdrawn)
        self.assertEqual(wallet.balance, 100 - price)
        self.assertTrue(tx.activity_ids)
        self.assertIn(self.user_finance, tx.activity_ids.user_id)
        self.assertIn(self.user_manager, tx.activity_ids.user_id)

    def test_sync_twice_creates_no_duplicates(self):
        self._topup(5000)
        line = self._line(self.topup_product, price=2000)
        payload = self._wallet_payload([line], wallet=2000, cash=0)
        order = self._sync(payload)
        self._sync(payload)
        order._earlydryer_wallet_sync()
        txs = self.Tx.search([("pos_order_id", "=", order.id)])
        self.assertEqual(len(txs), 2)
        self.assertEqual(sorted(txs.mapped("type")), ["spend", "topup"])
        self.assertEqual(self._balance(), 5000)

    def test_session_closing_matches_wallets(self):
        """GL Customer Advances = sum of the wallets once the session is closed."""
        other = self.env["res.partner"].create(
            {"name": "T Other", "phone": "+2348030000002"}
        )
        self._topup(6000)
        price = self._price(self.shirt_wi)
        order = self._sync(
            self._wallet_payload([self._line(self.shirt_wi)], wallet=price)
        )
        self._sync(
            self._wallet_payload(
                [self._line(self.topup_product, price=2500)], partner=other
            )
        )
        control = self._control()
        self.assertEqual(control.wallet_total - self.wallets_start, 6000 - price + 2500)
        # till transactions not accounted yet explain the difference
        self.assertEqual(control.pending_amount, 2500 - price)
        self.assertEqual(control.unexplained, 0)
        self._close_session(order.session_id)
        control = self._control()
        self.assertEqual(control.difference, 0)
        self.assertEqual(control.gl_balance - self.gl_start, 6000 - price + 2500)
        self.assertFalse(control.pending_transaction_ids)
        move_lines = order.session_id.move_id.line_ids.filtered(
            lambda line: line.account_id == self.advances
        )
        spend_line = move_lines.filtered(lambda line: line.debit)
        self.assertEqual(spend_line.partner_id, self.customer)
        self.assertEqual(spend_line.debit, price)
        topup_line = move_lines.filtered(lambda line: line.credit)
        self.assertEqual(topup_line.partner_id, other)
        self.assertEqual(topup_line.credit, 2500)
        # no revenue on the top-up, no receivable for the wallet payment
        receivable = self.customer.property_account_receivable_id
        self.assertFalse(
            order.session_id.move_id.line_ids.filtered(
                lambda line: (
                    line.account_id == receivable and line.partner_id == self.customer
                )
            )
        )

    def test_invoiced_order_wallet_payment_settles_invoice(self):
        self._topup(5000)
        price = self._price(self.shirt_wi)
        order = self._sync(
            self._wallet_payload(
                [self._line(self.shirt_wi)], wallet=price, to_invoice=True
            )
        )
        invoice = order.account_move
        self.assertTrue(invoice)
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(self._balance(), 5000 - price)
        self._close_session(order.session_id)
        control = self._control()
        self.assertEqual(control.difference, 0)

    def test_refund_of_topup_reverses_it(self):
        line = self._line(self.topup_product, price=3000)
        order = self._sync(self._wallet_payload([line]))
        topup = order.earlydryer_wallet_transaction_ids
        refund_line = self._line(
            self.topup_product,
            qty=-1,
            price=3000,
            refunded_orderline_id=order.lines.id,
        )
        refund_line[2]["price_subtotal"] = refund_line[2]["price_subtotal_incl"] = -3000
        refund = self._sync(self._wallet_payload([refund_line]))
        tx = refund.earlydryer_wallet_transaction_ids
        self.assertEqual(tx.type, "reversal")
        self.assertEqual(tx.reversed_id, topup)
        self.assertEqual(tx.signed_amount, -3000)
        self.assertEqual(self._balance(), 0)

    def test_load_balances_and_rpc(self):
        self._topup(4200)
        payload = self.config._earlydryer_wallet_payload()
        self.assertEqual(payload["balances"][str(self.customer.id)]["balance"], 4200)
        self.assertIn(self.pm_wallet.id, payload["method_ids"])
        empty = self.env["res.partner"].create({"name": "T No Wallet"})
        self.assertNotIn(str(empty.id), payload["balances"])
        order = self._sync(
            self._wallet_payload([self._line(self.shirt_wi)], wallet=1000)
        )
        result = self.Wallet.with_user(self.user_front_desk).get_balance(
            self.customer.id, [order.uuid, "t-unknown"]
        )
        self.assertEqual(result["balance"], 3200)
        self.assertEqual(result["synced_uuids"], [order.uuid])
