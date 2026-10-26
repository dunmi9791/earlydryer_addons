# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EarlydryerBranchShelfGenerate(models.TransientModel):
    _name = "earlydryer.branch.shelf.generate"
    _description = "Generate Earlydryer Shelves"

    branch_id = fields.Many2one("earlydryer.branch", required=True)
    prefix = fields.Char(required=True, default="A")
    separator = fields.Char(default="-")
    start = fields.Integer(string="Start Number", default=1)
    count = fields.Integer(default=10)
    padding = fields.Integer(
        string="Zero Padding", default=2, help="Number of digits, e.g. 2 gives A-01."
    )
    preview = fields.Char(compute="_compute_preview")

    @api.depends("prefix", "separator", "start", "count", "padding")
    def _compute_preview(self):
        for wizard in self:
            if wizard.count <= 0:
                wizard.preview = False
                continue
            first = wizard._shelf_name(wizard.start)
            last = wizard._shelf_name(wizard.start + wizard.count - 1)
            wizard.preview = first if wizard.count == 1 else f"{first} … {last}"

    @api.constrains("start", "count", "padding")
    def _check_numbers(self):
        for wizard in self:
            if wizard.start < 0 or wizard.count <= 0 or wizard.count > 500:
                raise ValidationError(
                    self.env._("Start must be positive and count between 1 and 500.")
                )
            if not 0 <= wizard.padding <= 6:
                raise ValidationError(
                    self.env._("Zero padding must be between 0 and 6.")
                )

    def _shelf_name(self, number):
        self.ensure_one()
        return (
            f"{(self.prefix or '').strip()}{self.separator or ''}"
            f"{str(number).zfill(self.padding)}"
        )

    def action_generate(self):
        self.ensure_one()
        self.branch_id._generate_shelves(
            self.prefix, self.start, self.count, self.padding, self.separator
        )
        return self.branch_id.action_view_shelves()
