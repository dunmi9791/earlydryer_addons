# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestUncollected(LaundryJobCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("earlydryer.uncollected_days", "14")
        params.set_param("earlydryer.uncollected_reminder_days", "3,7,12")
        cls.job = cls._create_job()
        for state in cls.PRODUCTION_PATH:
            cls.job.action_move_to(state, employee=cls.employee)
        cls.job.action_qc_pass(employee=cls.employee)
        cls.job.action_move_to("packed", employee=cls.employee)
        cls.job.shelf_id = cls.branch_1.shelf_ids[:1]
        cls.job.action_move_to("ready", employee=cls.employee)

    def _age(self, days):
        self.job.ready_on = fields.Datetime.now() - timedelta(days=days, hours=1)

    def _run_cron(self):
        sent = []
        original = type(self.Job)._earlydryer_send_uncollected_reminder

        def spy(job, day):
            sent.append((job.id, day))
            return original(job, day)

        with patch.object(type(self.Job), "_earlydryer_send_uncollected_reminder", spy):
            self.Job._cron_earlydryer_uncollected()
        return [day for job_id, day in sent if job_id == self.job.id]

    def test_reminders_once_then_uncollected(self):
        self._age(1)
        self.assertEqual(self._run_cron(), [])
        self._age(3)
        self.assertEqual(self._run_cron(), [3])
        self.assertEqual(self._run_cron(), [])
        self._age(8)
        self.assertEqual(self._run_cron(), [7])
        self._age(12)
        self.assertEqual(self._run_cron(), [12])
        self.assertEqual(self._run_cron(), [])
        self.assertEqual(self.job.uncollected_reminders_sent, "3,7,12")
        self.assertEqual(self.job.state, "ready")
        self._age(14)
        self.assertEqual(self._run_cron(), [])
        self.assertEqual(self.job.state, "uncollected")
        self.assertTrue(self.job.closed_on)
        self.assertIn("14 days", self._last_log(self.job).note)

    def test_missed_runs_send_latest_reminder_only(self):
        self._age(9)
        self.assertEqual(self._run_cron(), [7])
        self.assertEqual(self.job.uncollected_reminders_sent, "3,7")

    def test_delivery_jobs_are_not_reminded(self):
        self.job.fulfilment = "deliver"
        self._age(20)
        self._run_cron()
        self.assertEqual(self.job.state, "ready")

    def test_collect_after_uncollected(self):
        self._age(15)
        self._run_cron()
        self.assertEqual(self.job.state, "uncollected")
        with self.assertRaises(AccessError):
            self.job.with_user(self.user_front_desk).action_collect()
        self.job.with_user(self.user_manager).action_move_to(
            "collected", note="Customer came back"
        )
        self.assertEqual(self.job.state, "collected")

    def test_settings_validation(self):
        with self.assertRaises(ValidationError):
            self.env["res.config.settings"].create(
                {"earlydryer_uncollected_reminder_days": "3,x"}
            )
