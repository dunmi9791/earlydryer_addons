# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

from ..models.laundry_job import REWORK_STATES, STATES


class LaundryJobQcWizard(models.TransientModel):
    _name = "laundry.job.qc.wizard"
    _description = "Laundry Job Quality Check"

    job_id = fields.Many2one("laundry.job", required=True)
    result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail (rework)")], required=True, default="pass"
    )
    item_ids = fields.Many2many(
        "laundry.job.item",
        string="Items",
        domain="[('job_id', '=', job_id), ('qc_state', '!=', 'passed')]",
        help="Pass: leave empty to pass every item not passed yet.",
    )
    employee_id = fields.Many2one("hr.employee", string="Checked By", required=True)
    return_to_state = fields.Selection(
        [(state, label) for state, label in STATES if state in REWORK_STATES],
        string="Send Back To",
        default="washed",
    )
    note = fields.Text(string="Reason")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        job = self.env["laundry.job"].browse(
            res.get("job_id") or self.env.context.get("default_job_id")
        )
        if "employee_id" in fields_list and job and not res.get("employee_id"):
            res["employee_id"] = job._earlydryer_default_employee().id
        return res

    def action_confirm(self):
        self.ensure_one()
        if self.result == "pass":
            self.job_id.action_qc_pass(self.item_ids, self.employee_id)
        else:
            self.job_id.action_qc_fail(
                self.item_ids, self.employee_id, self.return_to_state, self.note
            )
        return {"type": "ir.actions.act_window_close"}
