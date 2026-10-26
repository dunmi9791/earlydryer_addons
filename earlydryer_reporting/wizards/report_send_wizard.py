# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

from ..tools import dates


class ReportSendWizard(models.TransientModel):
    _name = "earlydryer.report.send.wizard"
    _description = "Send Report Pack for a Period"
    subscription_id = fields.Many2one("earlydryer.report.subscription", required=True)
    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(required=True, default=fields.Date.context_today)

    def action_send(self):
        self.ensure_one()
        self.subscription_id.check_access("write")
        start, end, _ = dates(self.date_from, self.date_to)
        self.env["earlydryer.report.pack"]._schedule(
            self.subscription_id, start, end, manual=True
        )
        return {"type": "ir.actions.act_window_close"}
