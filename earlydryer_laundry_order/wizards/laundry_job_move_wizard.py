# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

from ..models.laundry_job import PRODUCTION_STATES, STATES


class LaundryJobMoveWizard(models.TransientModel):
    _name = "laundry.job.move.wizard"
    _description = "Move Laundry Jobs to a Stage"

    job_ids = fields.Many2many("laundry.job", string="Jobs", required=True)
    branch_ids = fields.Many2many(
        "earlydryer.branch", compute="_compute_branch_ids", string="Plants"
    )
    target_state = fields.Selection(STATES, string="Move To", required=True)
    employee_id = fields.Many2one(
        "hr.employee",
        string="Done By",
        help="Who did the work (may have no Odoo login).",
    )
    employee_required = fields.Boolean(compute="_compute_employee_required")
    item_ids = fields.Many2many(
        "laundry.job.item",
        string="Items",
        domain="[('job_id', 'in', job_ids)]",
        help="Leave empty when the move covers the whole job.",
    )
    note = fields.Text(
        help="Required when going backwards, skipping a stage or cancelling."
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "employee_id" in fields_list and not res.get("employee_id"):
            job_ids = res.get("job_ids") or self.env.context.get("default_job_ids")
            if job_ids and isinstance(job_ids[0], (list, tuple)):
                # [Command.set(ids)] from the client
                job_ids = job_ids[0][2]
            jobs = self.env["laundry.job"].browse(job_ids or [])
            if len(jobs.earlydryer_branch_id) <= 1:
                res["employee_id"] = jobs[:1]._earlydryer_default_employee().id
        return res

    @api.depends("job_ids")
    def _compute_branch_ids(self):
        for wizard in self:
            wizard.branch_ids = wizard.job_ids.earlydryer_branch_id

    @api.depends("target_state")
    def _compute_employee_required(self):
        for wizard in self:
            wizard.employee_required = wizard.target_state in PRODUCTION_STATES

    def action_confirm(self):
        self.ensure_one()
        self.job_ids.action_move_to(
            self.target_state,
            employee=self.employee_id,
            items=self.item_ids,
            note=self.note,
        )
        return {"type": "ir.actions.act_window_close"}
