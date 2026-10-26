# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerTagAssignWizardLine(models.TransientModel):
    _name = "earlydryer.tag.assign.wizard.line"
    _description = "Assign Pre-printed Tags: Garment"

    wizard_id = fields.Many2one(
        "earlydryer.tag.assign.wizard", required=True, ondelete="cascade"
    )
    item_id = fields.Many2one("laundry.job.item", string="Garment", required=True)
    job_id = fields.Many2one(related="item_id.job_id")
    piece_index = fields.Integer(related="item_id.piece_index")
    piece_count = fields.Integer(related="item_id.piece_count")
    colour = fields.Char(related="item_id.colour")
    tag_code = fields.Char(string="Tag", help="Scan the tag attached to the garment.")
