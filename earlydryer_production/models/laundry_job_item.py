# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

COLOUR_GROUPS = [
    ("whites", "Whites"),
    ("lights", "Lights"),
    ("darks", "Darks"),
    ("colours", "Colours"),
    ("delicates", "Delicates"),
    ("special", "Special (dry clean, leather...)"),
]
# item fields this module changes after intake (see _earlydryer_check_locked)
PRODUCTION_OPEN_FIELDS = {"colour_group"}


class LaundryJobItem(models.Model):
    _inherit = "laundry.job.item"

    colour_group = fields.Selection(
        COLOUR_GROUPS,
        compute="_compute_colour_group",
        store=True,
        readonly=False,
        index=True,
        help="Wash group chosen at sorting; proposed from the service type.",
    )
    wash_batch_ids = fields.Many2many(
        "earlydryer.wash.batch",
        "earlydryer_wash_batch_item_rel",
        "item_id",
        "batch_id",
        string="Batches",
        readonly=True,
        copy=False,
    )
    rework_ids = fields.One2many(
        "laundry.job.item.rework", "item_id", string="Reworks", readonly=True
    )

    @api.depends("service_type_id")
    def _compute_colour_group(self):
        for item in self:
            if not item.colour_group:
                item.colour_group = item.service_type_id.default_colour_group

    def _earlydryer_check_locked(self, jobs, fnames=None):
        if fnames is not None:
            fnames = set(fnames) - PRODUCTION_OPEN_FIELDS
            if not fnames:
                return
        return super()._earlydryer_check_locked(jobs, fnames)

    def _earlydryer_needs_stage(self, state):
        """Items going through ``state`` (washed, dried, ironed), not missing."""
        return self.filtered(
            lambda item: not item.missing and item.service_type_id._uses_stage(state)
        )
