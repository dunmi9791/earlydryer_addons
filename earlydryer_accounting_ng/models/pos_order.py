# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _prepare_invoice_vals(self):
        vals = super()._prepare_invoice_vals()
        branch = self.config_id.earlydryer_branch_id
        if branch:
            vals["earlydryer_branch_id"] = branch.id
        return vals
