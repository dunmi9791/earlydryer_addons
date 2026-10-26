# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerDailyCashWizard(models.TransientModel):
    _name = "earlydryer.daily.cash.wizard"
    _description = "Earlydryer Daily Cash Report"

    branch_ids = fields.Many2many(
        "earlydryer.branch",
        string="Plants",
        required=True,
        default=lambda self: self.env[
            "earlydryer.branch.mixin"
        ]._default_earlydryer_branch_id(),
    )
    date = fields.Date(required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        return self.branch_ids.action_earlydryer_daily_cash_report(self.date)
