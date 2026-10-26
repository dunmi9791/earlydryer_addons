# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.fields import Command

from ..models.laundry_job_stage_log import SOURCE_CTX


class EarlydryerSortWizard(models.TransientModel):
    _name = "earlydryer.sort.wizard"
    _description = "Earlydryer Sort Garments"

    job_id = fields.Many2one("laundry.job", required=True, readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Sorted By")
    move = fields.Boolean(
        string="Move to Sorted", default=True, help="Move the job once sorted."
    )
    line_ids = fields.One2many("earlydryer.sort.wizard.line", "wizard_id")

    @api.model
    def _earlydryer_open(self, job, employee_id=False, move=True):
        job.ensure_one()
        job.check_access("write")
        employee = employee_id or job._earlydryer_default_employee().id
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Sort %(job)s", job=job.name),
            "res_model": self._name,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_job_id": job.id,
                "default_employee_id": employee or False,
                "default_move": move and job.state == "tagged",
                "default_line_ids": [
                    Command.create(
                        {"item_id": item.id, "colour_group": item.colour_group}
                    )
                    for item in job.item_ids.filtered(lambda i: not i.missing)
                ],
            },
        }

    def action_confirm(self):
        self.ensure_one()
        for line in self.line_ids:
            if line.item_id.colour_group != line.colour_group:
                line.item_id.colour_group = line.colour_group
        if self.move and self.job_id.state != "sorted":
            source = self.env.context.get(SOURCE_CTX) or "board"
            job = self.job_id._earlydryer_clean_context()
            job.with_context(**{SOURCE_CTX: source}).action_move_to(
                "sorted", employee=self.employee_id
            )
        return {"type": "ir.actions.act_window_close"}
