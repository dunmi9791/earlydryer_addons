# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestCod(LogisticsCommon):
    def _out_for_delivery(self, job=None):
        job = job or self._sale_job()
        stop = self._book("delivery", job)
        trip = self._trip(stop)
        result = self._load(trip, job)
        self.assertEqual(result["result"], "ok", result["message"])
        self.Api.with_user(self.user_rider).rider_arrive(self._uuid(), stop.id)
        return job, stop, trip

    def _complete(self, stop, **vals):
        return self.Api.with_user(self.user_rider).rider_complete(
            self._uuid(), stop.id, {"recipient_name": "T", **vals}
        )

    def test_release_passes_for_assigned_cod_stop(self):
        job = self._sale_job()
        stop = self._book("delivery", job)
        self.assertTrue(stop.cod_amount > 0)
        # scheduled only: the release rule still applies
        with self.assertRaises(UserError):
            job.with_user(self.user_front_desk)._earlydryer_check_release()
        self._trip(stop, start=False)
        self.assertEqual(stop.state, "assigned")
        self.assertTrue(job.with_user(self.user_front_desk)._earlydryer_check_release())

    def test_release_fails_without_cod(self):
        self.branch_1.earlydryer_allow_cod = False
        job = self._sale_job()
        stop = self._book("delivery", job)
        self.assertEqual(stop.cod_amount, 0.0)
        trip = self._trip(stop)
        result = self._load(trip, job)
        self.assertEqual(result["result"], "refused")
        self.assertEqual(job.state, "ready")
        self.assertFalse(stop.loaded)
        self.assertTrue(stop.not_loaded)

    def test_full_collection_reconciled_and_delivered(self):
        job, stop, _trip = self._out_for_delivery()
        cod = stop.cod_amount
        self._complete(stop, collection_method="cash", cash_collected=cod)
        self.assertEqual(stop.state, "done")
        self.assertEqual(job.state, "delivered")
        payment = stop.cod_payment_id
        self.assertNotEqual(payment.state, "draft")
        self.assertEqual(payment.journal_id, self.branch_1.earlydryer_rider_journal_id)
        self.assertAlmostEqual(payment.amount, cod)
        credit = stop._earlydryer_cod_credit_lines()
        self.assertTrue(credit.reconciled)
        rider_line = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.branch_1.earlydryer_rider_account_id
        )
        self.assertAlmostEqual(rider_line.debit, cod)
        job.invalidate_recordset()
        self.assertEqual(job.amount_due, 0.0)
        self.assertEqual(stop.cash_short, 0.0)

    def test_short_collection_without_approval_refused(self):
        _job, stop, _trip = self._out_for_delivery()
        with self.assertRaises(UserError):
            self._complete(
                stop, collection_method="cash", cash_collected=stop.cod_amount - 500
            )
        self.assertEqual(stop.state, "arrived")

    def test_short_collection_with_manager_pin(self):
        job, stop, _trip = self._out_for_delivery()
        cod = stop.cod_amount
        # wrong PIN refused
        with self.assertRaises(UserError):
            self._complete(
                stop,
                collection_method="cash",
                cash_collected=cod - 500,
                approver_employee_id=self.emp_manager.id,
                pin="0000",
            )
        self._complete(
            stop,
            collection_method="cash",
            cash_collected=cod - 500,
            approver_employee_id=self.emp_manager.id,
            pin="9876",
        )
        self.assertEqual(stop.state, "done")
        self.assertEqual(job.state, "delivered")
        self.assertEqual(stop.credit_approver_employee_id, self.emp_manager)
        self.assertAlmostEqual(stop.cash_short, 500)
        self.assertTrue(job._earlydryer_credit_approved(500))
        self.assertTrue(
            self._alerts("earlydryer_logistics.rule_alert_rider_cash_short", stop)
        )

    def test_transfer_confirmed_creates_no_rider_cash(self):
        job, stop, _trip = self._out_for_delivery()
        self._complete(stop, collection_method="transfer_confirmed")
        self.assertEqual(stop.state, "done")
        self.assertFalse(stop.cod_payment_id)
        self.assertAlmostEqual(stop.transfer_amount, stop.cod_amount)
        to_match = self.Stop.search(
            [
                ("collection_method", "=", "transfer_confirmed"),
                ("transfer_matched", "=", False),
            ]
        )
        self.assertIn(stop, to_match)
        stop.with_user(self.user_finance).action_mark_transfer_matched()
        self.assertTrue(stop.transfer_matched)
