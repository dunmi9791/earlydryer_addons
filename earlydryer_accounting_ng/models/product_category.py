# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = "product.category"

    earlydryer_service_line_id = fields.Many2one(
        "account.analytic.account",
        string="Service Line",
        ondelete="restrict",
        domain=lambda self: self.env[
            "earlydryer.service.type"
        ]._earlydryer_service_line_domain(),
        help="Service line of the products of this category that have none of "
        "their own (e.g. Delivery fees).",
    )
