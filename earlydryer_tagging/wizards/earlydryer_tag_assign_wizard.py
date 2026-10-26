# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class EarlydryerTagAssignWizard(models.TransientModel):
    """Pre-printed plants: scan the physical tag of each garment in turn."""

    _name = "earlydryer.tag.assign.wizard"
    _description = "Assign Pre-printed Tags"

    job_ids = fields.Many2many("laundry.job", string="Jobs", readonly=True)
    line_ids = fields.One2many(
        "earlydryer.tag.assign.wizard.line", "wizard_id", string="Garments"
    )

    @api.model
    def _earlydryer_open(self, jobs):
        items = jobs.item_ids._earlydryer_needs_tag()
        wizard = self.create(
            {
                "job_ids": [Command.set(jobs.ids)],
                "line_ids": [Command.create({"item_id": item.id}) for item in items],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Scan the Tags"),
            "res_model": self._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_confirm(self):
        self.ensure_one()
        self.env["laundry.job"]._earlydryer_check_tag_right("assign")
        lines = self.line_ids.filtered("tag_code")
        if not lines:
            raise UserError(self.env._("Scan at least one tag."))
        codes = [line.tag_code.strip().upper() for line in lines]
        duplicates = {code for code in codes if codes.count(code) > 1}
        if duplicates:
            raise UserError(
                self.env._(
                    "Tag %(codes)s was scanned twice.",
                    codes=", ".join(sorted(duplicates)),
                )
            )
        Job = self.env["laundry.job"]
        for line in lines:
            line.item_id.tag_code = line.tag_code
            Job._earlydryer_scan_log(
                line.item_id.tag_code,
                "assign",
                "ok",
                job=line.item_id.job_id,
                item=line.item_id,
            )
        self.job_ids._earlydryer_tag_after_assign()
        return {"type": "ir.actions.act_window_close"}
