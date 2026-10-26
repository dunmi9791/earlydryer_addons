# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

MACHINE_TYPES = [
    ("washer", "Washer"),
    ("dryer", "Dryer"),
    ("iron_press", "Iron / Press"),
    ("steam_boiler", "Steam Boiler"),
    ("dry_clean_machine", "Dry-cleaning Machine"),
    ("other", "Other"),
]
# machines a batch of each type can run on
BATCH_MACHINE_TYPES = {
    "wash": ("washer", "dry_clean_machine"),
    "dry": ("dryer", "dry_clean_machine"),
}
MACHINE_STATUSES = [
    ("available", "Available"),
    ("in_use", "In Use"),
    ("down", "Down"),
]


class MaintenanceEquipment(models.Model):
    _name = "maintenance.equipment"
    _inherit = ["maintenance.equipment", "earlydryer.branch.mixin"]

    # optional here: equipment outside the plants (vehicles, office) has none
    earlydryer_branch_id = fields.Many2one(
        required=False,
        default=False,
        help="Earlydryer plant where this machine works. Empty for equipment "
        "that is not production equipment.",
    )
    earlydryer_machine_type = fields.Selection(MACHINE_TYPES, string="Machine Type")
    earlydryer_capacity_kg = fields.Float(
        string="Capacity (kg)", digits=(16, 1), help="Dry load capacity."
    )
    earlydryer_status = fields.Selection(
        MACHINE_STATUSES,
        string="Machine Status",
        compute="_compute_earlydryer_status",
        help="Down: an open corrective maintenance request exists. In Use: a "
        "wash or dry batch is running on it.",
    )

    def _compute_earlydryer_status(self):
        # requests and batches of other users count too: read with sudo
        down = set(
            self.env["maintenance.request"]
            .sudo()
            .search(
                [
                    ("equipment_id", "in", self.ids),
                    ("maintenance_type", "=", "corrective"),
                    ("stage_id.done", "=", False),
                    ("archive", "=", False),
                ]
            )
            .equipment_id.ids
        )
        in_use = set(
            self.env["earlydryer.wash.batch"]
            .sudo()
            .search([("machine_id", "in", self.ids), ("state", "=", "running")])
            .machine_id.ids
        )
        for equipment in self:
            if equipment.id in down:
                equipment.earlydryer_status = "down"
            elif equipment.id in in_use:
                equipment.earlydryer_status = "in_use"
            else:
                equipment.earlydryer_status = "available"

    def _earlydryer_strip_data(self):
        """What the machine status strip shows."""
        return [
            {
                "id": equipment.id,
                "name": equipment.name,
                "type": equipment.earlydryer_machine_type or "other",
                "type_label": dict(MACHINE_TYPES).get(
                    equipment.earlydryer_machine_type or "other"
                ),
                "status": equipment.earlydryer_status,
                "status_label": dict(MACHINE_STATUSES)[equipment.earlydryer_status],
                "capacity_kg": equipment.earlydryer_capacity_kg,
            }
            for equipment in self
        ]

    def action_earlydryer_report_breakdown(self):
        return self.env["earlydryer.breakdown.wizard"]._earlydryer_open(self[:1])
