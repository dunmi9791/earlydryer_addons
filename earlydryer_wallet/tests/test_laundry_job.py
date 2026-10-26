# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import WalletCommon


@tagged("post_install", "-at_install")
class TestLaundryJob(WalletCommon):
    def test_sale_job_paid_from_wallet_no_double_count(self):
        self._topup(100000)
        sale = self._create_sale([(self.shirt_wi, 2, None)], partner=self.customer)
        sale.action_confirm()
        job = sale.laundry_job_ids
        invoice = sale._create_invoices()
        invoice.action_post()
        total = job.amount_total
        self.assertTrue(job.earlydryer_wallet_can_pay)
        part = round(total / 2, 2)
        job._earlydryer_wallet_spend(part)
        job.invalidate_recordset()
        # reconciled with the invoice: counted once (invoice residual), not
        # again by the extra-paid hook
        self.assertEqual(job._earlydryer_extra_paid(), 0)
        self.assertAlmostEqual(job.amount_paid, part)
        self.assertAlmostEqual(job.amount_due, total - part)
        job._earlydryer_wallet_spend(job.amount_due)
        job.invalidate_recordset()
        self.assertEqual(job.amount_due, 0)
        self.assertEqual(self._balance(), 100000 - total)

    def test_pos_job_on_account_paid_from_wallet(self):
        """POS job left on the customer account, paid from the wallet before
        and after the session closes."""
        self._topup(5000)
        price = self._price(self.shirt_wi)
        order = self._sync(
            self._payload(
                [self._line(self.shirt_wi)], partner=self.customer, account=price
            )
        )
        job = order.earlydryer_job_id
        self.assertEqual(job.amount_due, price)
        # session still open: the receivable credit waits for the closing
        half = round(price / 2, 2)
        tx = job._earlydryer_wallet_spend(half)
        job.invalidate_recordset()
        self.assertEqual(job._earlydryer_extra_paid(), half)
        self.assertAlmostEqual(job.amount_due, price - half)
        self._close_session(order.session_id)
        job.invalidate_recordset()
        # reconciled at closing: still counted once
        self.assertTrue(tx._earlydryer_receivable_credit().reconciled)
        self.assertEqual(job._earlydryer_extra_paid(), 0)
        self.assertAlmostEqual(job.amount_due, price - half)
        # after the closing: reconciled at once
        tx2 = job._earlydryer_wallet_spend(job.amount_due)
        self.assertTrue(tx2._earlydryer_receivable_credit().reconciled)
        job.invalidate_recordset()
        self.assertEqual(job.amount_due, 0)
        self.assertEqual(self._balance(), 5000 - price)
        control = self._control()
        self.assertEqual(control.difference, 0)

    def test_job_shows_wallet_balance(self):
        self._topup(700)
        order = self._sync(
            self._payload([self._line(self.shirt_wi)], partner=self.customer)
        )
        self.assertEqual(order.earlydryer_job_id.earlydryer_wallet_balance, 700)
        self.assertFalse(order.earlydryer_job_id.earlydryer_wallet_can_pay)
