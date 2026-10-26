# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command

PLACEHOLDER_HELP = (
    " The rates shipped with the module are PLACEHOLDERS: confirm them with "
    "Earlydryer's tax adviser before go-live."
)
VENDOR_TYPES = [("company", "Company"), ("individual", "Individual")]


class EarlydryerWhtCategory(models.Model):
    """A kind of vendor bill on which withholding tax is deducted (rent,
    professional services...). Each rate becomes a negative purchase tax
    posting to WHT payable."""

    _name = "earlydryer.wht.category"
    _description = "Earlydryer WHT Category"
    _inherit = ["mail.thread"]
    _order = "sequence, name"
    _rec_names_search = ["name", "code"]

    name = fields.Char(required=True, translate=True, tracking=True)
    code = fields.Char(required=True, size=10, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    rate_company_vendor = fields.Float(
        string="Rate: Company Vendor (%)",
        digits=(5, 2),
        tracking=True,
        help="WHT rate on bills of incorporated vendors." + PLACEHOLDER_HELP,
    )
    rate_individual_vendor = fields.Float(
        string="Rate: Individual Vendor (%)",
        digits=(5, 2),
        tracking=True,
        help="WHT rate on bills of individuals and enterprises." + PLACEHOLDER_HELP,
    )
    tax_company_id = fields.Many2one(
        "account.tax",
        string="Tax (Company Vendor)",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    tax_individual_id = fields.Many2one(
        "account.tax",
        string="Tax (Individual Vendor)",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    note = fields.Text()

    _code_uniq = models.Constraint(
        "unique(code)", "The WHT category code must be unique."
    )

    @api.constrains("rate_company_vendor", "rate_individual_vendor")
    def _check_rates(self):
        for category in self:
            for rate in (category.rate_company_vendor, category.rate_individual_vendor):
                if rate < 0 or rate >= 100:
                    raise ValidationError(
                        self.env._(
                            "%(category)s: WHT rates are between 0 and 100%%.",
                            category=category.display_name,
                        )
                    )

    @api.model
    def _earlydryer_check_finance(self):
        user = self.env.user
        if not (
            self.env.su
            or user.has_group("earlydryer_base.group_finance")
            or user.has_group("earlydryer_base.group_admin")
        ):
            raise AccessError(self.env._("Only Finance manages WHT categories."))

    @api.model_create_multi
    def create(self, vals_list):
        self._earlydryer_check_finance()
        for vals in vals_list:
            if vals.get("code"):
                vals["code"] = vals["code"].strip().upper()
        categories = super().create(vals_list)
        categories._earlydryer_sync_taxes()
        return categories

    def write(self, vals):
        self._earlydryer_check_finance()
        if vals.get("code"):
            vals["code"] = vals["code"].strip().upper()
        res = super().write(vals)
        if {"rate_company_vendor", "rate_individual_vendor", "active", "name"} & set(
            vals
        ):
            self._earlydryer_sync_taxes()
        return res

    # ------------------------------------------------------------------
    # Taxes
    # ------------------------------------------------------------------

    def _earlydryer_tax_name(self, vendor_type, rate):
        self.ensure_one()
        label = dict(VENDOR_TYPES)[vendor_type]
        return self.env._(
            "WHT %(rate)s%% %(category)s (%(type)s)",
            rate=f"{rate:g}",
            category=self.name,
            type=label,
        )

    def _earlydryer_sync_taxes(self, companies=None):
        """Create or update the WHT taxes of each rate, for every company whose
        WHT payable account is set (the setup wizard sets it).

        A rate change on a tax already used would change posted history, so a
        new tax replaces it and the old one is archived. A zero rate means no
        tax.
        """
        if companies is None:
            companies = (
                self.env["res.company"]
                .sudo()
                .search([("earlydryer_wht_payable_account_id", "!=", False)])
            )
        Tax = self.env["account.tax"].sudo().with_context(active_test=False)
        for company in companies:
            group = company._earlydryer_tax_group(
                "tax_group_wht", self.env._("Withholding Tax")
            )
            account = company.earlydryer_wht_payable_account_id
            for category in self.sudo().with_context(active_test=False):
                for vendor_type, field, rate_field in (
                    ("company", "tax_company_id", "rate_company_vendor"),
                    ("individual", "tax_individual_id", "rate_individual_vendor"),
                ):
                    rate = category[rate_field]
                    key = f"wht_{category.id}_{vendor_type}"
                    tax = company._earlydryer_acc_ref(key)
                    if tax and tax.amount != -rate:
                        used = (
                            self.env["account.move.line"]
                            .sudo()
                            .search_count(
                                [
                                    "|",
                                    ("tax_ids", "in", tax.ids),
                                    ("tax_line_id", "=", tax.id),
                                ],
                                limit=1,
                            )
                        )
                        if used:
                            tax.active = False
                            tax = Tax
                        else:
                            tax.amount = -rate
                    active = category.active and rate > 0
                    if not tax and rate > 0:
                        tax = Tax.create(
                            category._earlydryer_tax_vals(
                                company, vendor_type, rate, group, account
                            )
                        )
                        company._earlydryer_acc_bind(key, tax)
                    if tax:
                        name = category._earlydryer_tax_name(vendor_type, rate)
                        tax_vals = {}
                        if tax.name != name:
                            tax_vals["name"] = name
                        if tax.active != active:
                            tax_vals["active"] = active
                        if tax_vals:
                            tax.write(tax_vals)
                    # one company in production: the category shows its taxes
                    if company == self.env.company or not category[field]:
                        if category[field] != tax:
                            super(EarlydryerWhtCategory, category).write(
                                {field: tax.id if tax else False}
                            )
        return True

    def _earlydryer_tax_vals(self, company, vendor_type, rate, group, account):
        self.ensure_one()
        repartition = [
            Command.create({"repartition_type": "base"}),
            Command.create({"repartition_type": "tax", "account_id": account.id}),
        ]
        return {
            "name": self._earlydryer_tax_name(vendor_type, rate),
            "description": f"WHT {rate:g}%",
            "invoice_label": self.env._("WHT %(rate)s%%", rate=f"{rate:g}"),
            "type_tax_use": "purchase",
            "amount_type": "percent",
            "amount": -rate,
            "price_include_override": "tax_excluded",
            "include_base_amount": False,
            "is_base_affected": False,
            "sequence": 90,
            "tax_group_id": group.id,
            "company_id": company.id,
            "country_id": company.account_fiscal_country_id.id,
            "earlydryer_wht_category_id": self.id,
            "earlydryer_wht_vendor_type": vendor_type,
            "invoice_repartition_line_ids": repartition,
            "refund_repartition_line_ids": [
                Command.create({"repartition_type": "base"}),
                Command.create({"repartition_type": "tax", "account_id": account.id}),
            ],
        }

    def _earlydryer_tax(self, vendor_type, company=None):
        """The active WHT tax of this category for ``vendor_type``."""
        self.ensure_one()
        company = company or self.env.company
        tax = company._earlydryer_acc_ref(f"wht_{self.id}_{vendor_type}")
        if tax and tax.active and self.active:
            return tax
        return self.env["account.tax"]

    def unlink(self):
        self._earlydryer_check_finance()
        if self.env["account.tax"].sudo().with_context(active_test=False).search_count(
            [("earlydryer_wht_category_id", "in", self.ids)], limit=1
        ):
            raise UserError(
                self.env._("Archive WHT categories that have taxes; do not delete them.")
            )
        return super().unlink()
