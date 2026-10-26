# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _earlydryer_service_line(self):
        """Service line of the product; surcharge and express lines take the
        one of their garment line."""
        self.ensure_one()
        product = self.product_id.sudo()
        if product.earlydryer_kind in ("surcharge", "express"):
            parent = self.earlydryer_parent_line_id
            if parent:
                return parent.product_id.sudo().earlydryer_service_line_id
        return product.earlydryer_service_line_id

    @api.depends("order_id.earlydryer_branch_id", "earlydryer_parent_line_id")
    def _compute_analytic_distribution(self):
        res = super()._compute_analytic_distribution()
        Model = self.env["account.analytic.distribution.model"]
        for line in self:
            if line.display_type:
                continue
            distribution = Model._get_distribution(
                {
                    "product_id": line.product_id.id,
                    "product_categ_id": line.product_id.categ_id.id,
                    "partner_id": line.order_id.partner_id.id,
                    "partner_category_id": line.order_id.partner_id.category_id.ids,
                    "company_id": line.company_id.id,
                    "earlydryer_branch_id": line.order_id.earlydryer_branch_id.id,
                    "earlydryer_service_line_id": line._earlydryer_service_line().id,
                }
            )
            if distribution:
                line.analytic_distribution = distribution
        return res
