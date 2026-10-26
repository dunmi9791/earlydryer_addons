# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestFees(LogisticsCommon):
    def test_fee_added_to_open_sale_order(self):
        job = self._sale_job()
        order = job.sale_order_id
        total, due = job.amount_total, job.amount_due
        stop = self._book("delivery", job)
        self.assertEqual(stop.state, "scheduled")
        self.assertEqual(stop.fee_amount, 1500)
        self.assertTrue(stop.fee_line_ref.startswith("sale.order.line,"))
        self.assertFalse(stop.fee_charged_move_id)
        fee_line = order.order_line.filtered(
            lambda line: line.product_id == self.env.ref("earlydryer_logistics.product_delivery_fee")
        )
        self.assertEqual(fee_line.price_unit, 1500)
        job.invalidate_recordset()
        self.assertAlmostEqual(job.amount_total, total + 1500)
        self.assertAlmostEqual(job.amount_due, due + 1500)
        self.assertAlmostEqual(stop.cod_amount, due + 1500)

    def test_fee_invoice_for_invoiced_job_counted_once(self):
        job = self._sale_job(paid=True)
        self.assertEqual(job.amount_due, 0.0)
        total = job.amount_total
        stop = self._book("delivery", job)
        invoice = stop.fee_charged_move_id
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(invoice.move_type, "out_invoice")
        self.assertEqual(invoice.earlydryer_logistics_job_id, job)
        self.assertEqual(invoice.amount_total, 1500)
        job.invalidate_recordset()
        self.assertAlmostEqual(job.amount_total, total + 1500)
        self.assertAlmostEqual(job.amount_due, 1500)
        self.assertAlmostEqual(stop.cod_amount, 1500)
        # charging again does nothing
        self.Stop._earlydryer_charge_fee(stop)
        self.assertEqual(len(job.earlydryer_fee_invoice_ids), 1)
        job.invalidate_recordset()
        self.assertAlmostEqual(job.amount_due, 1500)

    def test_fee_invoice_for_pos_job(self):
        job = self._pos_job()
        self.assertEqual(job.amount_due, 0.0)
        pos_total = job.amount_total
        stop = self._book("delivery", job)
        self.assertTrue(stop.fee_charged_move_id)
        job.invalidate_recordset()
        self.assertAlmostEqual(job.amount_total, pos_total + 1500)
        self.assertAlmostEqual(job.amount_due, 1500)

    def test_waive_needs_a_manager(self):
        job = self._sale_job()
        due = job.amount_due
        with self.assertRaises(UserError):
            self._book("delivery", job, fee_waived=True, fee_waive_reason="Loyal customer")
        stop = self._book(
            "delivery", job, user=self.user_manager, fee_waived=True,
            fee_waive_reason="Loyal customer",
        )
        self.assertTrue(stop.fee_waived)
        self.assertFalse(stop.fee_charged)
        self.assertAlmostEqual(stop.cod_amount, due)
        with self.assertRaises(AccessError):
            stop.with_user(self.user_front_desk).write({"fee_amount": 10})
        with self.assertRaises(AccessError):
            stop.with_user(self.user_front_desk).write({"cod_amount": 0})

    def test_unserved_area_needs_manual_fee_by_manager(self):
        customer = self.env["res.partner"].create(
            {"name": "T Far away", "earlydryer_area_id": self.area_unserved.id}
        )
        with self.assertRaises(UserError):
            self._book("pickup", partner=customer)
        stop = self._book("pickup", partner=customer, user=self.user_manager, fee_amount=2500)
        self.assertEqual(stop.fee_amount, 2500)
        self.assertEqual(stop.state, "scheduled")
        # a pickup has no job yet: the fee waits for the pricing at the plant
        self.assertFalse(stop.fee_charged)
