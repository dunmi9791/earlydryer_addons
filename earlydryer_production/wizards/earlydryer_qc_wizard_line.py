# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

from odoo.addons.earlydryer_laundry_order.models.laundry_job import (
    REWORK_STATES,
    STATES,
)


class EarlydryerQcWizardLine(models.TransientModel):
    _name = "earlydryer.qc.wizard.line"
    _description = "Earlydryer Quality Check Line"

    wizard_id = fields.Many2one(
        "earlydryer.qc.wizard", required=True, ondelete="cascade"
    )
    item_id = fields.Many2one("laundry.job.item", string="Garment", required=True)
    colour = fields.Char(related="item_id.colour")
    rework_count = fields.Integer(related="item_id.rework_count")
    result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail")], required=True, default="pass"
    )
    reason_id = fields.Many2one("earlydryer.rework.reason")
    return_state = fields.Selection(
        [(state, label) for state, label in STATES if state in REWORK_STATES],
        string="Back To",
        compute="_compute_return_state",
        store=True,
        readonly=False,
    )
    photo = fields.Image(max_width=1280, max_height=1280)
    note = fields.Char()

    @api.depends("reason_id")
    def _compute_return_state(self):
        for line in self:
            line.return_state = line.reason_id.default_return_state or "washed"
