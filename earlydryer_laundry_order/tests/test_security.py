# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestSecurity(LaundryJobCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job_1 = cls._create_job()
        cls.job_2 = cls._create_job(branch=cls.branch_2)
        cls.jobs = cls.job_1 | cls.job_2

    def test_front_desk_sees_own_plant(self):
        Job = self.Job.with_user(self.user_front_desk)
        self.assertEqual(Job.search([("id", "in", self.jobs.ids)]), self.job_1)
        with self.assertRaises(AccessError):
            self.job_2.with_user(self.user_front_desk).read(["name"])
        Log = self.Log.with_user(self.user_front_desk)
        self.assertEqual(
            Log.search([("job_id", "in", self.jobs.ids)]).job_id, self.job_1
        )
        Item = self.env["laundry.job.item"].with_user(self.user_front_desk)
        self.assertEqual(
            Item.search([("job_id", "in", self.jobs.ids)]).job_id, self.job_1
        )

    def test_finance_reads_both_plants(self):
        Job = self.Job.with_user(self.user_finance)
        self.assertEqual(Job.search([("id", "in", self.jobs.ids)]), self.jobs)
        with self.assertRaises(AccessError):
            self.job_1.with_user(self.user_finance).note = "x"

    def test_customer_request_schedules_todo(self):
        self.branch_1.manager_id = self.user_manager
        self.job_1.with_user(self.user_front_desk).action_customer_change_request()
        wizard = (
            self.env["laundry.job.request.wizard"]
            .with_user(self.user_front_desk)
            .create(
                {
                    "job_id": self.job_1.id,
                    "request_type": "cancel",
                    "description": "Wants the suit back unwashed",
                }
            )
        )
        wizard.action_confirm()
        activity = self.job_1.activity_ids
        self.assertEqual(activity.user_id, self.user_manager)
        self.assertIn("cancel", activity.summary)

    def test_request_fallback_to_branch_managers(self):
        self.branch_1.manager_id = False
        self.job_1._earlydryer_customer_request("change", "Add starch")
        self.assertIn(self.user_manager, self.job_1.activity_ids.user_id)
