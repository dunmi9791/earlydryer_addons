# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestPromised(LaundryJobCommon):
    def test_promised_from_catalogue(self):
        job = self._create_job([(self.shirt_wi, 1, None), (self.shirt_dc, 1, None)])
        expected = self.Catalog.promised_datetime(
            self.shirt_wi | self.shirt_dc, self.branch_1, start=job.received_on
        )
        self.assertEqual(job.promised_on, expected)
        # express while received: recomputed
        job.express = True
        expected = self.Catalog.promised_datetime(
            self.shirt_wi | self.shirt_dc,
            self.branch_1,
            express=True,
            start=job.received_on,
        )
        self.assertEqual(job.promised_on, expected)

    def test_promised_editable_by_manager_only_after_intake(self):
        job = self._create_job()
        later = job.promised_on + timedelta(days=1)
        # at intake the front desk may adjust it
        job.with_user(self.user_front_desk).promised_on = later
        self.assertEqual(job.promised_on, later)
        job.action_move_to("tagged")
        with self.assertRaises(AccessError):
            job.with_user(self.user_front_desk).promised_on = later + timedelta(days=1)
        job.with_user(self.user_manager).promised_on = later + timedelta(days=1)
        self.assertEqual(job.promised_on, later + timedelta(days=1))
        # no longer recomputed after intake
        job.express = True
        self.assertEqual(job.promised_on, later + timedelta(days=1))

    def test_overdue(self):
        job = self._create_job()
        job.promised_on = job.received_on - timedelta(hours=1)
        self.assertTrue(job.is_overdue)
        self.assertIn(job, self.Job.search([("is_overdue", "=", True)]))
