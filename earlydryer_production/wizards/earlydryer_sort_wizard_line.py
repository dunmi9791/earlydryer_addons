# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

from ..models.laundry_job_item import COLOUR_GROUPS


class EarlydryerSortWizardLine(models.TransientModel):
    _name = "earlydryer.sort.wizard.line"
    _description = "Earlydryer Sort Garments Line"

    wizard_id = fields.Many2one(
        "earlydryer.sort.wizard", required=True, ondelete="cascade"
    )
    item_id = fields.Many2one("laundry.job.item", string="Garment", required=True)
    colour = fields.Char(related="item_id.colour")
    service_type_id = fields.Many2one(related="item_id.service_type_id")
    colour_group = fields.Selection(COLOUR_GROUPS)
