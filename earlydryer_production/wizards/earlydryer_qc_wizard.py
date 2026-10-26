# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from odoo.addons.earlydryer_laundry_order.models.laundry_job import REWORK_STATES


class EarlydryerQcWizard(models.TransientModel):
    """Quality check of a job, garment by garment (replaces the job-level
    wizard of earlydryer_laundry_order on the job form)."""

    _name = "earlydryer.qc.wizard"
    _description = "Earlydryer Quality Check"

    job_id = fields.Many2one("laundry.job", required=True, readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Checked By", required=True)
    line_ids = fields.One2many("earlydryer.qc.wizard.line", "wizard_id")
    passed_count = fields.Integer(compute="_compute_counts")
    failed_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids.result")
    def _compute_counts(self):
        for wizard in self:
            results = wizard.line_ids.mapped("result")
            wizard.passed_count = results.count("pass")
            wizard.failed_count = results.count("fail")

    @api.model
    def _earlydryer_open(self, job, employee_id=False):
        job.ensure_one()
        job._earlydryer_check_qc_right()
        if job.state != "qc":
            raise UserError(self.env._("Job %(job)s is not in QC.", job=job.name))
        employee = employee_id or job._earlydryer_default_employee().id
        # defaults, not a saved wizard: "Checked By" may still be empty (a
        # tablet login has no employee) and is picked in the dialog
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Quality Check %(job)s", job=job.name),
            "res_model": self._name,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_job_id": job.id,
                "default_employee_id": employee or False,
                "default_line_ids": [
                    Command.create({"item_id": item.id})
                    for item in job.item_ids.filtered(
                        lambda i: i.qc_state != "passed" and not i.missing
                    )
                ],
            },
        }

    def _earlydryer_apply(self):
        self.ensure_one()
        job = self.job_id._earlydryer_clean_context()
        passed = self.line_ids.filtered(lambda line: line.result == "pass")
        failed = self.line_ids.filtered(lambda line: line.result == "fail")
        if passed:
            job.action_qc_pass(passed.item_id, self.employee_id)
        if failed:
            return_state = min(failed.mapped("return_state"), key=REWORK_STATES.index)
            job.action_qc_fail(
                failed.item_id,
                self.employee_id,
                return_to_state=return_state,
                details={
                    line.item_id.id: {
                        "reason_id": line.reason_id.id,
                        "note": line.note,
                        "photo": line.photo,
                    }
                    for line in failed
                },
            )
        return failed

    def action_confirm(self):
        self._earlydryer_apply()
        return {"type": "ir.actions.act_window_close"}

    def action_confirm_pack(self):
        """All passed: pass them, then on to packing."""
        self.ensure_one()
        if self._earlydryer_apply():
            raise UserError(
                self.env._("Some garments failed: the job cannot be packed.")
            )
        job = self.job_id._earlydryer_clean_context()
        action = job.action_earlydryer_qc_pack(self.employee_id)
        if isinstance(action, dict):
            return action
        return {"type": "ir.actions.act_window_close"}
