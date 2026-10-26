# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerBranchShelf(models.Model):
    _name = "earlydryer.branch.shelf"
    _description = "Earlydryer Collection Shelf"
    _order = "branch_id, sequence, name"

    name = fields.Char(required=True, help="Shelf or rack label, e.g. A-03.")
    branch_id = fields.Many2one(
        "earlydryer.branch",
        required=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="branch_id.company_id", store=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    capacity = fields.Integer(help="Optional number of orders the shelf can hold.")
    note = fields.Text()

    _name_branch_uniq = models.Constraint(
        "unique(branch_id, name)",
        "The shelf name must be unique per branch.",
    )
