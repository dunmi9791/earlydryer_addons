# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    earlydryer_branch_ids = fields.One2many(
        "earlydryer.branch",
        "warehouse_id",
        string="Earlydryer Branches (technical)",
        context={"active_test": False},
    )
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        compute="_compute_earlydryer_branch_id",
        store=True,
        index=True,
    )

    @api.depends("earlydryer_branch_ids")
    def _compute_earlydryer_branch_id(self):
        for warehouse in self:
            # a warehouse belongs to at most one branch (checked on the branch)
            warehouse.earlydryer_branch_id = warehouse.earlydryer_branch_ids[:1]
