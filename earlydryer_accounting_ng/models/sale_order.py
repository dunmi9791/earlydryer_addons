# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.earlydryer_branch_id:
            vals["earlydryer_branch_id"] = self.earlydryer_branch_id.id
        return vals
