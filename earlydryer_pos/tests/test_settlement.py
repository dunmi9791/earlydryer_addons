# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import EarlydryerPosCommon


@tagged("post_install", "-at_install")
class TestSettlement(EarlydryerPosCommon):
    def test_settlement_credits_receivable_and_reconciles(self):
        intake = self._sync(
            self._payload([self._line(self.shirt_wi)], paid=400, account=600)
        )
        job = intake.earlydryer_job_id
        self._close_session(intake.session_id)
        open_lines = intake._earlydryer_receivable_lines()
        self.assertEqual(sum(open_lines.mapped("amount_residual")), 600)

        # collection: the customer pays the balance in cash at the counter
        settlement = self._line(
            self.product_settlement,
            price=600,
            earlydryer_settlement_job_ref=str(job.id),
        )
        order = self._sync(self._payload([settlement]))
        self.assertEqual(order.earlydryer_settlement_job_ids, job)
        self.assertFalse(order.earlydryer_job_id)
        # paid at the till: nothing due any more, before the session closes
        job.invalidate_recordset()
        self.assertEqual(job.amount_due, 0)
        self.assertEqual(job.amount_total, 1000)

        session = order.session_id
        self._close_session(session)
        receivable = self.partner.commercial_partner_id.property_account_receivable_id
        credit = session.move_id.line_ids.filtered("earlydryer_settlement")
        self.assertEqual(len(credit), 1)
        self.assertEqual(credit.account_id, receivable)
        self.assertEqual(credit.partner_id, self.partner.commercial_partner_id)
        self.assertEqual(credit.credit, 600)
        self.assertTrue(credit.reconciled)
        self.assertTrue(all(open_lines.mapped("reconciled")))
        # no revenue on the settlement
        revenue = session.move_id.line_ids.filtered(
            lambda line: line.account_id.internal_group == "income"
        )
        self.assertFalse(revenue)
        job.invalidate_recordset()
        self.assertEqual(job.amount_due, 0)
