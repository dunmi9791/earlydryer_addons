# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ProductionCommon


@tagged("post_install", "-at_install")
class TestSorting(ProductionCommon):
    def test_default_from_service_type(self):
        job = self._create_job([(self.shirt_wi, 1, None), (self.shirt_dc, 1, None)])
        groups = {item.service_type_id: item.colour_group for item in job.item_ids}
        self.assertEqual(groups, {self.svc_wi: "whites", self.svc_dc: "special"})

    def test_colour_group_required(self):
        self.svc_wi.default_colour_group = False
        job = self._job_in("tagged")
        self.assertFalse(job.item_ids.colour_group)
        self.assertEqual(job.unsorted_item_count, 1)
        with self.assertRaisesRegex(UserError, "colour group"):
            job.action_move_to("sorted", employee=self.employee)
        # production staff set the group after intake (open field)
        job.item_ids.with_user(self.user_production).colour_group = "lights"
        job.with_user(self.user_production).action_move_to(
            "sorted", employee=self.employee
        )
        self.assertEqual(job.state, "sorted")

    def test_not_required_when_off(self):
        self.svc_wi.default_colour_group = False
        self.branch_1.require_sorting_colour_group = False
        job = self._job_in("sorted")
        self.assertEqual(job.state, "sorted")

    def test_sort_wizard(self):
        self.svc_wi.default_colour_group = False
        job = self._job_in("tagged", [(self.shirt_wi, 2, None)])
        Job = self.Job.with_user(self.user_production)
        action = Job.earlydryer_board_open_sort(job.id, employee_id=self.employee.id)
        wizard = (
            self.env["earlydryer.sort.wizard"]
            .with_user(self.user_production)
            .with_context(**action["context"])
            .create({})
        )
        self.assertEqual(len(wizard.line_ids), 2)
        wizard.line_ids[0].colour_group = "darks"
        with self.assertRaises(UserError):
            wizard.with_user(self.user_production).action_confirm()
        wizard.line_ids[1].colour_group = "colours"
        wizard.with_user(self.user_production).action_confirm()
        self.assertEqual(
            sorted(job.item_ids.mapped("colour_group")), ["colours", "darks"]
        )
        self.assertEqual(job.state, "sorted")
        log = self._last_log(job)
        self.assertEqual((log.source, log.employee_id), ("board", self.employee))
