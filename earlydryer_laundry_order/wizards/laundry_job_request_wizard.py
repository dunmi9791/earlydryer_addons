# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class LaundryJobRequestWizard(models.TransientModel):
    _name = "laundry.job.request.wizard"
    _description = "Customer Change or Cancellation Request"

    job_id = fields.Many2one("laundry.job", required=True)
    request_type = fields.Selection(
        [("change", "Change"), ("cancel", "Cancel")], required=True, default="change"
    )
    description = fields.Text(string="Request", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.job_id._earlydryer_customer_request(self.request_type, self.description)
        return {"type": "ir.actions.act_window_close"}
