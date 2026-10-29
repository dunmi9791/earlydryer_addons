# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

# income account of the company used by each product kind, when the product
# has no income account of its own. settlement and wallet_topup keep the
# accounts their modules set.
KIND_INCOME_FIELDS = {
    "laundry": "earlydryer_laundry_income_account_id",
    "surcharge": "earlydryer_laundry_income_account_id",
    "express": "earlydryer_laundry_income_account_id",
    "retail": "earlydryer_retail_income_account_id",
}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    earlydryer_service_line_id = fields.Many2one(
        "account.analytic.account",
        string="Service Line",
        compute="_compute_earlydryer_service_line_id",
        store=True,
        readonly=False,
        ondelete="restrict",
        domain=lambda self: self.env[
            "earlydryer.service.type"
        ]._earlydryer_service_line_domain(),
        help="Laundry products: the service line of their service type. Retail "
        "products: Retail. Surcharge and express lines take the service line of "
        "the garment line they belong to.",
    )

    @api.depends(
        "earlydryer_kind",
        "earlydryer_service_type_id.earlydryer_service_line_id",
        "categ_id.earlydryer_service_line_id",
    )
    def _compute_earlydryer_service_line_id(self):
        retail = self.env.ref(
            "earlydryer_accounting_ng.service_line_retail", raise_if_not_found=False
        )
        for template in self:
            line = template.categ_id.earlydryer_service_line_id
            if template.earlydryer_kind == "laundry":
                line = template.earlydryer_service_type_id.earlydryer_service_line_id
            elif template.earlydryer_kind == "retail" and not line:
                line = retail
            elif template.earlydryer_kind in ("settlement", "wallet_topup"):
                line = False
            template.earlydryer_service_line_id = line or False

    def _get_product_accounts(self):
        """The product's own accounts first, then the company's account of
        its Earlydryer kind (set by the setup wizard), then core's fallbacks."""
        accounts = super()._get_product_accounts()
        company = self.company_id or self.env.company
        field = KIND_INCOME_FIELDS.get(self.earlydryer_kind)
        if field and company[field] and not self.property_account_income_id:
            accounts["income"] = company[field]
        cogs = company.earlydryer_retail_cogs_account_id
        if (
            self.earlydryer_kind == "retail"
            and cogs
            and not self.property_account_expense_id
        ):
            accounts["expense"] = cogs
        return accounts

    @api.model
    def _earlydryer_recompute_service_lines(self):
        """Called by the data once the service lines exist (the stored field
        is first computed at install, before they are loaded)."""
        templates = self.with_context(active_test=False).search(
            [("earlydryer_kind", "!=", False)]
        )
        templates._compute_earlydryer_service_line_id()
        return True
