# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestQc(LaundryJobCommon):
    def test_qc_fail_rework_then_pass(self):
        job = self._create_job([(self.shirt_wi, 2, None)])
        self._walk(job, self.PRODUCTION_PATH)
        first, second = job.item_ids
        job_qc = job.with_user(self.user_qc)
        job_qc.action_qc_pass(first, self.employee)
        job_qc.action_qc_fail(second, self.employee, "washed", "Collar stain")
        self.assertEqual(job.state, "washed")
        self.assertEqual(first.qc_state, "passed")
        self.assertEqual(second.qc_state, "rework")
        self.assertEqual(second.rework_count, 1)
        log = self._last_log(job)
        self.assertEqual((log.from_state, log.to_state), ("qc", "washed"))
        self.assertEqual(log.item_ids, second)
        self.assertEqual(log.user_id, self.user_qc)

        # back through the plant: packing waits for the reworked item
        self._walk(job_qc, ["dried", "ironed", "qc"])
        with self.assertRaises(UserError):
            job_qc.action_move_to("packed", employee=self.employee)
        job_qc.action_qc_pass(employee=self.employee)
        job_qc.action_move_to("packed", employee=self.employee)
        self.assertEqual(job.state, "packed")
        self.assertEqual(second.rework_count, 1)

    def test_qc_fail_requires_note_and_target(self):
        job = self._create_job()
        self._walk(job, self.PRODUCTION_PATH)
        with self.assertRaises(UserError):
            job.action_qc_fail(job.item_ids, self.employee, "washed", "")
        with self.assertRaises(UserError):
            job.action_qc_fail(job.item_ids, self.employee, "packed", "Bad")

    def test_missing_item_blocks_packing(self):
        job = self._create_job([(self.shirt_wi, 2, None)])
        self._walk(job, [*self.PRODUCTION_PATH, "qc_pass"])
        job.item_ids[0].with_user(self.user_front_desk).missing = True
        self.assertIn("missing", job.message_ids[0].body)
        with self.assertRaises(UserError):
            job.action_move_to("packed", employee=self.employee)
        job.item_ids[0].missing = False
        job.action_move_to("packed", employee=self.employee)
        self.assertEqual(job.state, "packed")
