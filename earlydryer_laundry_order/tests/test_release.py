# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestRelease(LaundryJobCommon):
    def _ready_job(self, **kwargs):
        job = self._create_job(**kwargs)
        self._walk(job, [*self.PRODUCTION_PATH, "qc_pass", "packed"])
        job.shelf_id = job.earlydryer_branch_id.shelf_ids[:1]
        job.action_move_to("ready", employee=self.employee)
        return job

    def test_unpaid_needs_credit_approval(self):
        job = self._ready_job()
        self.assertEqual(job.amount_due, 1000.0)
        self.assertTrue(job.is_unpaid)
        self.assertIn(job, self.Job.search([("is_unpaid", "=", True)]))
        job_fd = job.with_user(self.user_front_desk)
        with self.assertRaises(UserError):
            job_fd.action_collect()
        self.assertEqual(job.state, "ready")

        action = job_fd.action_request_credit_approval()
        self.assertEqual(action["context"]["default_value"], 1000.0)
        wizard = (
            self.env["earlydryer.approval.request.wizard"]
            .with_user(self.user_front_desk)
            .with_context(action["context"])
            .create({"reason": "Regular customer, pays on Friday"})
        )
        wizard.action_request()
        request = self.env["earlydryer.approval.request"].search(
            [("res_model", "=", "laundry.job"), ("res_id", "=", job.id)]
        )
        self.assertEqual(request.state, "pending")
        with self.assertRaises(UserError):
            job_fd.action_collect()
        request.with_user(self.user_manager).action_approve()
        self.assertIn("Credit of", job.message_ids[0].body)
        job_fd.action_collect()
        self.assertEqual(job.state, "collected")

    def test_manager_self_approves_credit(self):
        job = self._ready_job(fulfilment="deliver")
        job.with_user(self.user_manager).action_out_for_delivery()
        self.assertEqual(job.state, "out_for_delivery")
        request = self.env["earlydryer.approval.request"].search(
            [("res_model", "=", "laundry.job"), ("res_id", "=", job.id)]
        )
        self.assertEqual(request.state, "approved")
        job.with_user(self.user_front_desk).action_delivered()
        self.assertEqual(job.state, "delivered")

    def test_credit_needs_manager_without_rule(self):
        self.env.ref(
            "earlydryer_laundry_order.approval_rule_credit_laundry_job"
        ).active = False
        job = self._ready_job()
        with self.assertRaises(UserError):
            job.with_user(self.user_front_desk).action_collect()
        job.with_user(self.user_manager).action_collect()
        self.assertEqual(job.state, "collected")

    def test_paid_job_collects_without_approval(self):
        job = self._ready_job()
        sale = job.sale_order_id
        invoice = sale._create_invoices()
        invoice.action_post()
        self.assertEqual(job.amount_paid, 0.0)
        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids
        ).create({})._create_payments()
        job.invalidate_recordset(["amount_paid", "amount_due", "is_unpaid"])
        self.assertEqual(job.amount_paid, 1000.0)
        self.assertEqual(job.amount_due, 0.0)
        job.with_user(self.user_front_desk).action_collect()
        self.assertEqual(job.state, "collected")
        self.assertFalse(
            self.env["earlydryer.approval.request"].search_count(
                [("res_model", "=", "laundry.job"), ("res_id", "=", job.id)]
            )
        )
