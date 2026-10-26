# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import ProductionCommon


@tagged("post_install", "-at_install")
class TestMachine(ProductionCommon):
    def test_status(self):
        self.assertEqual(self.washer.earlydryer_status, "available")
        job = self._job_in("sorted")
        batch = self._batch(job.item_ids)
        batch.action_start()
        self.washer.invalidate_recordset(["earlydryer_status"])
        self.assertEqual(self.washer.earlydryer_status, "in_use")
        batch.action_done()
        self.washer.invalidate_recordset(["earlydryer_status"])
        self.assertEqual(self.washer.earlydryer_status, "available")
        # preventive requests do not stop the machine; corrective ones do
        preventive = self.Request.create(
            {
                "name": "Service",
                "equipment_id": self.washer.id,
                "maintenance_type": "preventive",
                "maintenance_team_id": self.team.id,
            }
        )
        self.washer.invalidate_recordset(["earlydryer_status"])
        self.assertEqual(self.washer.earlydryer_status, "available")
        preventive.unlink()
        corrective = self.Request.create(
            {
                "name": "Leak",
                "equipment_id": self.washer.id,
                "maintenance_type": "corrective",
                "maintenance_team_id": self.team.id,
            }
        )
        self.washer.invalidate_recordset(["earlydryer_status"])
        self.assertEqual(self.washer.earlydryer_status, "down")
        done_stage = self.env["maintenance.stage"].search(
            [("done", "=", True)], limit=1
        )
        corrective.stage_id = done_stage
        self.washer.invalidate_recordset(["earlydryer_status"])
        self.assertEqual(self.washer.earlydryer_status, "available")

    def test_report_breakdown(self):
        Wizard = self.env["earlydryer.breakdown.wizard"].with_user(self.user_production)
        action = self.washer.with_user(
            self.user_production
        ).action_earlydryer_report_breakdown()
        wizard = Wizard.with_context(**action["context"]).create(
            {"description": "Drum stuck", "employee_id": self.employee.id}
        )
        self.assertEqual(wizard.equipment_id, self.washer)
        request = wizard._earlydryer_create_request()
        self.assertEqual(request.maintenance_type, "corrective")
        self.assertEqual(request.maintenance_team_id, self.team)
        self.assertIn("Drum stuck", request.description)
        self.assertIn(self.employee.name, request.description)
        self.washer.invalidate_recordset(["earlydryer_status"])
        self.assertEqual(self.washer.earlydryer_status, "down")
        # the strip on the board shows it
        data = self.Job.with_user(self.user_production).earlydryer_board_data(
            self.branch_1.id
        )
        strip = {m["id"]: m["status"] for m in data["machines"]}
        self.assertEqual(strip[self.washer.id], "down")
        with self.assertRaises(AccessError):
            self.env["earlydryer.breakdown.wizard"].with_user(
                self.user_rider
            )._earlydryer_open(self.washer)

    def test_staff_read_own_plant_machines(self):
        other = self.Equipment.create(
            {
                "name": "T Washer P2",
                "earlydryer_branch_id": self.branch_2.id,
                "earlydryer_machine_type": "washer",
            }
        )
        Equipment = self.Equipment.with_user(self.user_production)
        found = Equipment.search([("id", "in", (self.washer | other).ids)])
        self.assertEqual(found, self.washer)
