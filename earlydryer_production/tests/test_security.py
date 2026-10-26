# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import ProductionCommon


@tagged("post_install", "-at_install")
class TestSecurity(ProductionCommon):
    def test_production_stops_before_packing(self):
        job = self._job_in("ironed")
        Job = job.with_user(self.user_production)
        Job.action_move_to("qc", employee=self.employee)
        job.action_qc_pass(employee=self.employee)
        with self.assertRaises(AccessError):
            Job.action_move_to("packed", employee=self.employee)
        res = self.Job.with_user(self.user_production).earlydryer_board_move(
            [job.id], "packed", self.employee.id
        )
        self.assertFalse(res["results"][0]["ok"])
        self.assertEqual(job.state, "qc")
        # QC staff go on
        job.with_user(self.user_qc).action_move_to("packed", employee=self.employee)
        self.assertEqual(job.state, "packed")
        with self.assertRaises(AccessError):
            job.with_user(self.user_production).action_qc_pass(employee=self.employee)

    def test_rider_cannot_move(self):
        job = self._job_in("tagged")
        with self.assertRaises(AccessError):
            job.with_user(self.user_rider).action_move_to(
                "sorted", employee=self.employee
            )
        res = self.Job.with_user(self.user_rider).earlydryer_board_move(
            [job.id], "sorted", self.employee.id
        )
        self.assertFalse(res["results"][0]["ok"])
        self.assertEqual(job.state, "tagged")

    def test_front_desk_cannot_configure_machines(self):
        action = self.env.ref(
            "earlydryer_production.maintenance_equipment_action_earlydryer_config"
        )
        user_groups = self.user_front_desk.all_group_ids
        self.assertFalse(action.group_ids & user_groups)
        menu = self.env.ref("earlydryer_production.menu_earlydryer_bm_machines")
        visible = (
            self.env["ir.ui.menu"].with_user(self.user_front_desk)._visible_menu_ids()
        )
        self.assertNotIn(menu.id, visible)
        with self.assertRaises(AccessError):
            self.washer.with_user(self.user_front_desk).earlydryer_capacity_kg = 50
        with self.assertRaises(AccessError):
            self.Equipment.with_user(self.user_front_desk).create(
                {"name": "X", "earlydryer_branch_id": self.branch_1.id}
            )
        # the Branch Manager configures the plant's machines
        self.washer.with_user(self.user_manager).earlydryer_capacity_kg = 50
        self.assertEqual(self.washer.earlydryer_capacity_kg, 50)

    def test_rework_records_branch_rule(self):
        job = self._job_in("qc")
        job.action_qc_fail(job.item_ids, self.employee, reason=self.reason_iron)
        other = self._job_in("qc", branch=self.branch_2)
        other.action_qc_fail(other.item_ids, self.employee_2, reason=self.reason_iron)
        Rework = self.Rework.with_user(self.user_front_desk)
        self.assertEqual(Rework.search([]).job_id, job)
