# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerRiderHandoverWizard(models.TransientModel):
    _name = "earlydryer.rider.handover.wizard"
    _description = "Earlydryer Rider Cash Handover"

    branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        required=True,
        default=lambda self: self.env[
            "earlydryer.branch.mixin"
        ]._default_earlydryer_branch_id(),
    )
    currency_id = fields.Many2one(related="branch_id.currency_id")
    rider_id = fields.Many2one("hr.employee", required=True)
    amount = fields.Monetary(required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    reference = fields.Char()

    def action_handover(self):
        self.ensure_one()
        move = self.env["account.move"]._earlydryer_rider_handover(
            self.branch_id,
            self.amount,
            self.rider_id,
            date=self.date,
            ref=self.reference,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
        }
