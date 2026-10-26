# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from odoo.addons.earlydryer_tagging.tests.common import TaggingCommon


@tagged("post_install", "-at_install")
class ProductionCommon(TaggingCommon):
    """Tagging test data plus machines, badges and production settings.

    Plant 1: both modes, batches on, colour groups required, no packing scan.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Batch = cls.env["earlydryer.wash.batch"]
        cls.Equipment = cls.env["maintenance.equipment"]
        cls.Request = cls.env["maintenance.request"]
        cls.Reason = cls.env["earlydryer.rework.reason"]
        cls.Rework = cls.env["laundry.job.item.rework"]
        cls.Ident = cls.env["earlydryer.tablet.identification"]
        cls.branch_1.write(
            {
                "production_mode": "both",
                "use_wash_batches": True,
                "tag_require_packing_scan": False,
                # LaundryJobCommon turns these off for the earlier modules' tests
                "require_sorting_colour_group": True,
                "qc_reason_required": True,
            }
        )
        cls.branch_2.write({"production_mode": "tablet"})
        cls.svc_wi.default_colour_group = "whites"
        cls.svc_dc.default_colour_group = "special"
        cls.svc_io.default_colour_group = "lights"
        cls.employee.write({"barcode": "TBADGE-1", "pin": "1234"})
        cls.employee_2.write({"barcode": "TBADGE-2", "pin": "5678"})
        cls.employee_floating = cls.Employee.create(
            {"name": "T Floater", "barcode": "TBADGE-F", "pin": "9999"}
        )
        cls.team = cls.env["maintenance.team"].create({"name": "T Team"})
        cls.washer = cls.Equipment.create(
            {
                "name": "T Washer",
                "earlydryer_branch_id": cls.branch_1.id,
                "earlydryer_machine_type": "washer",
                "earlydryer_capacity_kg": 2.0,
                "maintenance_team_id": cls.team.id,
            }
        )
        cls.dryer = cls.Equipment.create(
            {
                "name": "T Dryer",
                "earlydryer_branch_id": cls.branch_1.id,
                "earlydryer_machine_type": "dryer",
                "maintenance_team_id": cls.team.id,
            }
        )
        cls.reason_iron = cls.Reason.create(
            {
                "name": "T Poor ironing",
                "code": "TIRON",
                "default_return_state": "ironed",
            }
        )
        cls.reason_stain = cls.Reason.create(
            {"name": "T Stain", "code": "TSTAIN", "default_return_state": "sorted"}
        )
        cls.reason_damage = cls.Reason.create(
            {
                "name": "T Damage",
                "code": "TDMG",
                "default_return_state": "ironed",
                "is_damage": True,
            }
        )

    @classmethod
    def _job_in(cls, state, lines=None, branch=None, **kwargs):
        """A job walked to ``state`` along the production path."""
        job = cls._create_job(lines, branch, **kwargs)
        employee = (
            cls.employee if (branch or cls.branch_1) == cls.branch_1 else cls.employee_2
        )
        if job.tag_mode == "preprinted":
            for number, item in enumerate(job.item_ids._earlydryer_needs_tag(), 1):
                item.tag_code = f"TT{job.id % 100:02d}{number:02d}"
        path = ["tagged", "sorted", "washed", "dried", "ironed", "qc"]
        if state in path:
            for step in path[: path.index(state) + 1]:
                if job.state != step and job._earlydryer_move_kind(step) == "normal":
                    job.action_move_to(step, employee=employee)
        return job

    def _batch(self, items, batch_type="wash", machine=None, **vals):
        return self.Batch.create(
            {
                "earlydryer_branch_id": self.branch_1.id,
                "batch_type": batch_type,
                "machine_id": (machine or self.washer).id,
                "employee_id": self.employee.id,
                "item_ids": [(6, 0, items.ids)],
                **vals,
            }
        )
