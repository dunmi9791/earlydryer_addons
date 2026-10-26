# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields
from odoo.tests import tagged

from .common import EarlydryerPosCommon


@tagged("post_install", "-at_install")
class TestCollection(EarlydryerPosCommon):
    def _ready_job(self, paid=None, account=0.0):
        order = self._sync(
            self._payload([self._line(self.shirt_wi)], paid=paid, account=account)
        )
        return self._make_ready(order.earlydryer_job_id)

    def _submit(self, job, mode="paid", uuid=None, **extra):
        vals = {
            "uuid": uuid or f"t-collect-{job.id}-{mode}",
            "job_id": job.id,
            "employee_id": self.emp_front_desk.id,
            "mode": mode,
            "approver_employee_id": False,
            "amount_due": job.amount_due,
            "collected_on": fields.Datetime.to_string(fields.Datetime.now()),
            "settlement_order_uuid": False,
            **extra,
        }
        return self.Collection.with_user(self.user_front_desk).earlydryer_pos_submit(
            self.config.id, [vals]
        )

    def test_paid_job_collected(self):
        job = self._ready_job()
        info = self.Job.with_user(self.user_front_desk).earlydryer_pos_collection_info(
            job.id, self.config.id
        )
        self.assertEqual(info["shelf"], job.shelf_id.name)
        lookup = self.Job.with_user(self.user_front_desk).earlydryer_pos_lookup(
            job.pos_order_id.pos_reference, self.config.id
        )
        self.assertEqual([j["id"] for j in lookup["jobs"]], [job.id])
        [result] = self._submit(job)
        self.assertEqual(result["status"], "done")
        self.assertEqual(job.state, "collected")
        self.assertFalse(job.earlydryer_released_unpaid)
        log = job.stage_log_ids.filtered(lambda line: line.to_state == "collected")
        self.assertEqual(log.employee_id, self.emp_front_desk)
        # sent twice (retry after a lost answer): recorded once
        [again] = self._submit(job)
        self.assertEqual(again["status"], "done")
        self.assertEqual(self.Collection.search_count([("job_id", "=", job.id)]), 1)

    def test_unpaid_without_approval_flagged(self):
        job = self._ready_job(paid=0, account=1000)
        self.assertEqual(job.amount_due, 1000)
        [result] = self._submit(job)
        self.assertEqual(result["status"], "released_unpaid")
        # what happened at the counter is kept
        self.assertEqual(job.state, "collected")
        self.assertTrue(job.earlydryer_released_unpaid)
        self.assertIn(self.user_manager, job.activity_ids.user_id)

    def test_manager_credit(self):
        job = self._ready_job(paid=0, account=1000)
        [result] = self._submit(
            job, mode="credit", approver_employee_id=self.emp_manager.id
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(job.state, "collected")
        self.assertFalse(job.earlydryer_released_unpaid)
        request = self.Request.search(
            [
                ("res_model", "=", "laundry.job"),
                ("res_id", "=", job.id),
                ("approval_type", "=", "credit"),
                ("state", "=", "approved"),
            ]
        )
        self.assertTrue(request)
        self.assertEqual(request[0].value, 1000)
        self.assertEqual(request[0].decided_by_id, self.user_manager)
        log = self.env["earlydryer.pos.pin.approval"].search([("job_id", "=", job.id)])
        self.assertEqual(log.approval_type, "credit")
        self.assertEqual(log.employee_id, self.emp_manager)

    def test_not_ready_is_refused(self):
        order = self._sync(self._payload([self._line(self.shirt_wi)]))
        job = order.earlydryer_job_id
        [result] = self._submit(job)
        self.assertEqual(result["status"], "refused")
        self.assertNotEqual(job.state, "collected")

    def test_settlement_waits_for_its_order(self):
        job = self._ready_job(paid=0, account=1000)
        [result] = self._submit(
            job, mode="settlement", settlement_order_uuid="t-not-synced"
        )
        self.assertEqual(result["status"], "pending")
        self.assertFalse(self.Collection.search([("job_id", "=", job.id)]))
