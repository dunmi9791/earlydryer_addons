# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import WalletCommon


@tagged("post_install", "-at_install")
class TestAutoApply(WalletCommon):
    def _sale_invoice(self):
        sale = self._create_sale([(self.shirt_wi, 2, None)], partner=self.customer)
        sale.action_confirm()
        invoice = sale._create_invoices()
        invoice.action_post()
        return sale, invoice

    def test_applied_when_on(self):
        self.company.earlydryer_wallet_auto_apply = True
        self._topup(500)
        sale, invoice = self._sale_invoice()
        tx = invoice.earlydryer_wallet_transaction_ids
        self.assertEqual(tx.amount, min(500, invoice.amount_total))
        self.assertEqual(invoice.amount_residual, invoice.amount_total - tx.amount)
        self.assertEqual(tx.laundry_job_id, sale.laundry_job_ids)
        self.assertEqual(self._balance(), 500 - tx.amount)

    def test_not_applied_when_off(self):
        self._topup(500)
        _sale, invoice = self._sale_invoice()
        self.assertFalse(invoice.earlydryer_wallet_transaction_ids)
        self.assertEqual(self._balance(), 500)

    def test_never_on_plain_or_pos_invoices(self):
        self.company.earlydryer_wallet_auto_apply = True
        self._topup(5000)
        # not from a sales order
        invoice = self._invoice(1000)
        self.assertFalse(invoice.earlydryer_wallet_transaction_ids)
        # POS invoice
        payload = self._payload(
            [self._line(self.shirt_wi)], partner=self.customer, to_invoice=True
        )
        order = self._sync(payload)
        self.assertTrue(order.account_move)
        self.assertFalse(order.account_move.earlydryer_wallet_transaction_ids)
        self.assertEqual(self._balance(), 5000)
