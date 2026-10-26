# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    earlydryer_wht_category_id = fields.Many2one(
        "earlydryer.wht.category",
        string="WHT Category",
        ondelete="restrict",
        tracking=True,
        help="Withholding tax deducted from this vendor's bills. Leave empty for "
        "exempt vendors.",
    )
    earlydryer_wht_vendor_type = fields.Selection(
        [("company", "Company"), ("individual", "Individual")],
        string="WHT Vendor Type",
        compute="_compute_earlydryer_wht_vendor_type",
        store=True,
        readonly=False,
        tracking=True,
        help="Company or individual: the WHT rates differ.",
    )

    @api.depends("is_company")
    def _compute_earlydryer_wht_vendor_type(self):
        for partner in self:
            if not partner.earlydryer_wht_vendor_type:
                partner.earlydryer_wht_vendor_type = (
                    "company" if partner.is_company else "individual"
                )

    @property
    def _commercial_fields(self):
        return super()._commercial_fields + [
            "earlydryer_wht_category_id",
            "earlydryer_wht_vendor_type",
        ]

    def _earlydryer_wht_tax(self, company=None):
        """WHT tax of this vendor (commercial entity), or an empty recordset."""
        partner = self.commercial_partner_id
        category = partner.earlydryer_wht_category_id
        if not category:
            return self.env["account.tax"]
        return category._earlydryer_tax(
            partner.earlydryer_wht_vendor_type or "company", company=company
        )

    def action_earlydryer_customer_statement(self):
        return self.env.ref(
            "earlydryer_accounting_ng.action_report_customer_statement"
        ).report_action(self)
