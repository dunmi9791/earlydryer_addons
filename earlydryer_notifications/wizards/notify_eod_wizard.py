# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import uuid

from odoo import fields, models
from odoo.exceptions import AccessError


class NotifyEodWizard(models.TransientModel):
    _name = "earlydryer.notify.eod.wizard"
    _description = "Resend End of Day Report"
    branch_id = fields.Many2one("earlydryer.branch", required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)

    def action_send(self):
        self.ensure_one()
        if not self.env.user.has_group("earlydryer_base.group_branch_manager"):
            raise AccessError(self.env._("Only managers can resend EOD reports."))
        self.branch_id.check_access("read")
        self.env["earlydryer.notify.eod.report"].sudo()._schedule(
            self.branch_id, self.date, run_key=str(uuid.uuid4())
        )
        return {"type": "ir.actions.act_window_close"}
