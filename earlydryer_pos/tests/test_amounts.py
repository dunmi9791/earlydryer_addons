# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import EarlydryerPosCommon


@tagged("post_install", "-at_install")
class TestAmounts(EarlydryerPosCommon):
    def test_full_payment_nothing_due(self):
        order = self._sync(self._payload([self._line(self.shirt_wi, qty=2)]))
        job = order.earlydryer_job_id
        self.assertEqual(job.amount_total, 2000)
        self.assertEqual(job.amount_due, 0)
        self.assertFalse(job.is_unpaid)

    def test_partial_payment_on_account(self):
        order = self._sync(
            self._payload([self._line(self.shirt_wi, qty=2)], paid=500, account=1500)
        )
        job = order.earlydryer_job_id
        self.assertEqual(job.amount_paid, 500)
        self.assertEqual(job.amount_due, 1500)
        # closing the session posts the customer's receivable: still due
        session = order.session_id
        self._close_session(session)
        receivable = order._earlydryer_receivable_lines()
        self.assertEqual(receivable.partner_id, self.partner.commercial_partner_id)
        self.assertEqual(sum(receivable.mapped("amount_residual")), 1500)
        job.invalidate_recordset()
        self.assertEqual(job.amount_due, 1500)
        # Finance records a bank payment of 1000 outside the POS
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner.id,
                "amount": 1000,
                "journal_id": self.env["account.journal"]
                .search(
                    [("type", "=", "bank"), ("company_id", "=", self.env.company.id)],
                    limit=1,
                )
                .id,
            }
        )
        payment.action_post()
        payment_line = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == receivable.account_id
        )
        (payment_line | receivable).reconcile()
        job.invalidate_recordset()
        self.assertEqual(job.amount_due, 500)

    def test_two_orders_same_customer_paid_oldest_first(self):
        first = self._sync(
            self._payload([self._line(self.shirt_wi)], paid=0, account=1000)
        )
        second = self._sync(
            self._payload([self._line(self.shirt_wi)], paid=0, account=1000)
        )
        self._close_session(first.session_id)
        lines = first._earlydryer_receivable_lines()
        self.assertEqual(sum(lines.mapped("amount_residual")), 2000)
        # a credit note of 1000 settles the oldest order first
        journal = self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        move = self.env["account.move"].create(
            {
                "journal_id": journal.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "account_id": lines[0].account_id.id,
                            "partner_id": self.partner.id,
                            "credit": 1000,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "account_id": self.journal_cash.default_account_id.id,
                            "debit": 1000,
                        },
                    ),
                ],
            }
        )
        move.action_post()
        (
            move.line_ids.filtered(lambda line: line.account_id == lines[0].account_id)
            | lines
        ).reconcile()
        (first | second).earlydryer_job_id.invalidate_recordset()
        self.assertEqual(first.earlydryer_job_id.amount_due, 0)
        self.assertEqual(second.earlydryer_job_id.amount_due, 1000)
