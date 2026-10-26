# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerTagReplaceWizard(models.TransientModel):
    _name = "earlydryer.tag.replace.wizard"
    _description = "Replace a Garment Tag"

    item_id = fields.Many2one(
        "laundry.job.item", string="Garment", required=True, readonly=True
    )
    old_code = fields.Char(related="item_id.tag_code", string="Current Tag")
    tag_mode = fields.Selection(related="item_id.tag_mode")
    new_code = fields.Char(
        string="New Tag",
        help="Scan the new tag. Printed plants: leave empty to print a new code.",
    )
    reason = fields.Text(required=True, help="Lost, damaged, unreadable...")

    def action_confirm(self):
        self.ensure_one()
        self.item_id._earlydryer_replace_tag(self.reason, self.new_code)
        if self.item_id.tag_mode == "printed" and not self.new_code:
            return self.item_id.job_id._earlydryer_print_tags(self.item_id)
        return {"type": "ir.actions.act_window_close"}
