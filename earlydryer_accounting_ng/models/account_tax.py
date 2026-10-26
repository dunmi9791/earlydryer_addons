# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class AccountTax(models.Model):
    _inherit = "account.tax"

    earlydryer_wht_category_id = fields.Many2one(
        "earlydryer.wht.category",
        string="WHT Category",
        index="btree_not_null",
        ondelete="restrict",
        readonly=True,
        help="Withholding tax generated from this category.",
    )
    earlydryer_wht_vendor_type = fields.Selection(
        [("company", "Company"), ("individual", "Individual")],
        string="WHT Vendor Type",
        readonly=True,
    )
