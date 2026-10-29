# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    earlydryer_kind = fields.Selection(
        selection_add=[("delivery_fee", "Delivery Fee")],
        ondelete={"delivery_fee": "set null"},
    )
