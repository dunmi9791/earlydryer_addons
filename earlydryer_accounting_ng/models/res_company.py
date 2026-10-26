# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import fields, models
from odoo.fields import Command, Domain

_logger = logging.getLogger(__name__)

XMLID_MODULE = "earlydryer_accounting_ng"
# product kinds whose sales tax follows the VAT switch
VAT_PRODUCT_KINDS = ("laundry", "surcharge", "express", "retail")


class ResCompany(models.Model):
    _inherit = "res.company"

    # ------------------------------------------------------------------
    # Tax status
    # ------------------------------------------------------------------
    earlydryer_vat_registered = fields.Boolean(
        string="VAT Registered",
        help="Earlydryer charges VAT (7.5%, to confirm). Run 'Apply VAT setting' "
        "after changing it: only new documents are affected.",
    )
    earlydryer_prices_include_vat = fields.Boolean(
        string="Prices Include VAT",
        default=True,
        help="Walk-in prices are quoted VAT-inclusive (to confirm).",
    )
    earlydryer_sale_tax_id = fields.Many2one(
        "account.tax",
        string="Sales VAT",
        check_company=True,
        domain=[("type_tax_use", "=", "sale")],
    )
    earlydryer_purchase_tax_id = fields.Many2one(
        "account.tax",
        string="Purchase VAT",
        check_company=True,
        domain=[("type_tax_use", "=", "purchase")],
    )
    earlydryer_vat_applied_state = fields.Char(
        string="VAT Setting Applied",
        readonly=True,
        help="Registered / price-included pair the last 'Apply VAT setting' used.",
    )
    earlydryer_einvoice_enabled = fields.Boolean(
        string="FIRS E-invoicing",
        help="Held until the tax status and the FIRS requirements are known. "
        "When set, posted customer invoices call _earlydryer_einvoice_submit().",
    )
    earlydryer_tax_authority_id = fields.Many2one(
        "res.partner",
        string="Tax Authority",
        help="Partner paid by WHT remittances (FIRS or the state revenue service).",
    )
    earlydryer_invoice_footer = fields.Text(
        string="Invoice Footer Note", translate=True
    )

    # ------------------------------------------------------------------
    # Accounts set by the setup wizard
    # ------------------------------------------------------------------
    earlydryer_laundry_income_account_id = fields.Many2one(
        "account.account",
        string="Laundry Service Revenue",
        check_company=True,
        help="Income of laundry, surcharge and express products without an "
        "income account of their own.",
    )
    earlydryer_retail_income_account_id = fields.Many2one(
        "account.account", string="Retail Sales Revenue", check_company=True
    )
    earlydryer_delivery_income_account_id = fields.Many2one(
        "account.account", string="Delivery Fee Revenue", check_company=True
    )
    earlydryer_discount_account_id = fields.Many2one(
        "account.account",
        string="Sales Discounts",
        check_company=True,
        help="Only when discounts are shown separately (to confirm).",
    )
    earlydryer_retail_cogs_account_id = fields.Many2one(
        "account.account", string="Cost of Retail Goods Sold", check_company=True
    )
    earlydryer_consumables_account_id = fields.Many2one(
        "account.account", string="Laundry Consumables", check_company=True
    )
    earlydryer_cash_diff_account_id = fields.Many2one(
        "account.account", string="Cash Over and Short", check_company=True
    )
    earlydryer_cash_transit_account_id = fields.Many2one(
        "account.account",
        string="Cash in Transit to Bank",
        check_company=True,
        help="Debited by lodgements, credited when the bank statement line is "
        "reconciled.",
    )
    earlydryer_gateway_account_id = fields.Many2one(
        "account.account", string="Payment Gateway Clearing", check_company=True
    )
    earlydryer_wht_payable_account_id = fields.Many2one(
        "account.account", string="WHT Payable", check_company=True
    )
    earlydryer_wht_receivable_account_id = fields.Many2one(
        "account.account",
        string="WHT Receivable",
        check_company=True,
        help="WHT deducted by corporate customers from Earlydryer's invoices.",
    )
    earlydryer_opening_equity_account_id = fields.Many2one(
        "account.account",
        string="Opening Balance Equity",
        check_company=True,
        help="Takes the difference of an unbalanced opening trial balance.",
    )
    earlydryer_opening_journal_id = fields.Many2one(
        "account.journal",
        string="Opening Balances Journal",
        check_company=True,
        domain=[("type", "=", "general")],
    )
    earlydryer_gateway_journal_id = fields.Many2one(
        "account.journal",
        string="Payment Gateway Journal",
        check_company=True,
        domain=[("type", "=", "bank")],
    )

    # ------------------------------------------------------------------
    # XML ids of the records created for a company
    # ------------------------------------------------------------------

    def _earlydryer_acc_xmlid(self, key):
        self.ensure_one()
        safe = "".join(char if char.isalnum() else "_" for char in key.lower())
        return f"{self.id}_{safe}"

    def _earlydryer_acc_ref(self, key):
        self.ensure_one()
        return self.env.ref(
            f"{XMLID_MODULE}.{self._earlydryer_acc_xmlid(key)}",
            raise_if_not_found=False,
        )

    def _earlydryer_acc_bind(self, key, record):
        """Give ``record`` the XML id ``earlydryer_accounting_ng.<company>_<key>``
        (moved to ``record`` when it pointed to another one)."""
        self.ensure_one()
        IrModelData = self.env["ir.model.data"].sudo()
        name = self._earlydryer_acc_xmlid(key)
        data = IrModelData.search(
            [("module", "=", XMLID_MODULE), ("name", "=", name)], limit=1
        )
        if data:
            if (data.model, data.res_id) != (record._name, record.id):
                data.write({"model": record._name, "res_id": record.id})
        else:
            IrModelData.create(
                {
                    "module": XMLID_MODULE,
                    "name": name,
                    "model": record._name,
                    "res_id": record.id,
                    "noupdate": True,
                }
            )
        return record

    def _earlydryer_chart_ref(self, xmlid):
        """Record of the installed chart template (``tax_received``,
        ``l10n_ng_vat_out_7_5``...) or an empty value."""
        self.ensure_one()
        if not self.chart_template:
            return False
        ChartTemplate = self.env["account.chart.template"].with_company(self)
        return ChartTemplate.ref(xmlid, raise_if_not_found=False)

    def _earlydryer_is_ng_chart(self):
        self.ensure_one()
        return self.chart_template == "ng"

    def _earlydryer_misc_journal(self):
        """Miscellaneous operations journal of the chart (not the Wallet or
        Opening balances journals)."""
        self.ensure_one()
        journal = self._earlydryer_chart_ref("general")
        if not journal:
            journal = self.env["account.journal"].sudo().search(
                [
                    ("company_id", "=", self.id),
                    ("type", "=", "general"),
                    ("earlydryer_role", "=", False),
                    ("id", "!=", self.earlydryer_wallet_journal_id.id),
                ],
                limit=1,
            )
        return journal

    def _earlydryer_param(self, key, default=""):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(f"earlydryer_accounting_ng.{key}", default)
        )

    # ------------------------------------------------------------------
    # VAT
    # ------------------------------------------------------------------

    def _earlydryer_vat_rate(self):
        return float(self._earlydryer_param("vat_rate", "7.5") or 0.0)

    def _earlydryer_tax_group(self, key, name):
        self.ensure_one()
        group = self._earlydryer_acc_ref(key)
        if group:
            return group
        group = (
            self.env["account.tax.group"]
            .sudo()
            .create(
                {
                    "name": name,
                    "company_id": self.id,
                    "country_id": self.account_fiscal_country_id.id,
                }
            )
        )
        return self._earlydryer_acc_bind(key, group)

    def _earlydryer_vat_tax_vals(self, tax_use, account, name):
        self.ensure_one()
        group = self._earlydryer_tax_group(
            "tax_group_vat", self.env._("Earlydryer VAT")
        )
        repartition = [
            Command.create({"repartition_type": "base"}),
            Command.create({"repartition_type": "tax", "account_id": account.id}),
        ]
        return {
            "name": name,
            "description": name,
            "type_tax_use": tax_use,
            "amount_type": "percent",
            "amount": self._earlydryer_vat_rate(),
            "tax_group_id": group.id,
            "company_id": self.id,
            "country_id": self.account_fiscal_country_id.id,
            "invoice_repartition_line_ids": repartition,
            "refund_repartition_line_ids": [
                Command.create({"repartition_type": "base"}),
                Command.create({"repartition_type": "tax", "account_id": account.id}),
            ],
        }

    def _earlydryer_ensure_vat_taxes(self, output_account=None, input_account=None):
        """Sales and purchase VAT: l10n_ng's 7.5% taxes when the company uses
        the Nigerian chart, otherwise taxes created here (once).

        Sales VAT exists twice, price-included and price-excluded, so that
        switching the setting never changes a tax already used on documents.
        Sets ``earlydryer_sale_tax_id`` to the one matching the setting.
        """
        Tax = self.env["account.tax"].sudo().with_context(active_test=False)
        for company in self.sudo():
            taxes = {}
            for key, l10n_key, tax_use, account, label, include in (
                (
                    "tax_vat_sale_excl",
                    "l10n_ng_vat_out_7_5",
                    "sale",
                    output_account,
                    self.env._("VAT 7.5%"),
                    "tax_excluded",
                ),
                (
                    "tax_vat_sale_incl",
                    False,
                    "sale",
                    output_account,
                    self.env._("VAT 7.5% (price included)"),
                    "tax_included",
                ),
                (
                    "tax_vat_purchase",
                    "l10n_ng_vat_in_7_5",
                    "purchase",
                    input_account,
                    self.env._("VAT 7.5% (purchases)"),
                    False,
                ),
            ):
                tax = company._earlydryer_acc_ref(key)
                if not tax and l10n_key and company._earlydryer_is_ng_chart():
                    tax = company._earlydryer_chart_ref(l10n_key) or Tax
                    if tax and include and tax.price_include != (
                        include == "tax_included"
                    ):
                        tax = Tax
                    if tax:
                        company._earlydryer_acc_bind(key, tax)
                if not tax and key == "tax_vat_sale_incl" and taxes.get(
                    "tax_vat_sale_excl"
                ):
                    tax = taxes["tax_vat_sale_excl"].copy(
                        {"name": label, "price_include_override": include}
                    )
                    company._earlydryer_acc_bind(key, tax)
                if not tax:
                    account = account or company._earlydryer_default_vat_account(
                        tax_use
                    )
                    vals = company._earlydryer_vat_tax_vals(tax_use, account, label)
                    if include:
                        vals["price_include_override"] = include
                    tax = Tax.create(vals)
                    company._earlydryer_acc_bind(key, tax)
                    _logger.info("Tax %s created for %s.", label, company.name)
                taxes[key] = tax
            sale_tax = taxes[
                "tax_vat_sale_incl"
                if company.earlydryer_prices_include_vat
                else "tax_vat_sale_excl"
            ]
            vals = {}
            if company.earlydryer_sale_tax_id != sale_tax:
                vals["earlydryer_sale_tax_id"] = sale_tax.id
            if not company.earlydryer_purchase_tax_id:
                vals["earlydryer_purchase_tax_id"] = taxes["tax_vat_purchase"].id
            if vals:
                company.write(vals)
        return True

    def _earlydryer_vat_sale_taxes(self):
        """Both sales VAT taxes (included and excluded) of the company."""
        self.ensure_one()
        taxes = self.env["account.tax"]
        for key in ("tax_vat_sale_excl", "tax_vat_sale_incl"):
            taxes |= self._earlydryer_acc_ref(key) or taxes
        return taxes | self.earlydryer_sale_tax_id

    def _earlydryer_default_vat_account(self, tax_use):
        """VAT output / input account of the chart (Tax Received / Tax Paid)."""
        self.ensure_one()
        key = "tax_received" if tax_use == "sale" else "tax_paid"
        account = self._earlydryer_chart_ref(key)
        if not account and self._earlydryer_is_ng_chart():
            account = self._earlydryer_chart_ref(f"l10n_ng_{key}")
        if not account:
            account_type = "liability_current" if tax_use == "sale" else "asset_current"
            Account = self.env["account.account"].with_company(self)
            account = Account.search(
                [*Account._check_company_domain(self), ("account_type", "=", account_type)],
                limit=1,
            )
        return account

    def _earlydryer_vat_products(self):
        self.ensure_one()
        Template = self.env["product.template"].sudo().with_context(active_test=False)
        delivery = self.env.ref(
            "earlydryer_accounting_ng.product_category_delivery",
            raise_if_not_found=False,
        )
        domain = Domain("earlydryer_kind", "in", VAT_PRODUCT_KINDS)
        if delivery:
            domain |= Domain("categ_id", "child_of", delivery.id)
        domain &= Domain("company_id", "in", [self.id, False])
        return Template.search(domain)

    def _earlydryer_apply_vat_setting(self):
        """Put the sales VAT on the products sold by Earlydryer (or take it
        off), set the price-included flag, the default taxes and the POS
        configs. Never touches posted documents; safe to run again.

        :returns: summary lines (list of str)
        """
        summary = []
        for company in self.sudo():
            company._earlydryer_ensure_vat_taxes()
            sale_tax = company.earlydryer_sale_tax_id
            purchase_tax = company.earlydryer_purchase_tax_id
            registered = company.earlydryer_vat_registered
            vat_taxes = company._earlydryer_vat_sale_taxes()
            if registered and not sale_tax.active:
                sale_tax.active = True
            products = company._earlydryer_vat_products()
            changed = 0
            for template in products:
                taxes = template.taxes_id & vat_taxes
                others = template.taxes_id - vat_taxes
                wanted = sale_tax if registered else self.env["account.tax"]
                if taxes != wanted:
                    template.taxes_id = [Command.set((others | wanted).ids)]
                    changed += 1
            summary.append(
                self.env._(
                    "%(company)s: sales VAT %(state)s on %(changed)s of %(count)s "
                    "products.",
                    company=company.name,
                    state=self.env._("set") if registered else self.env._("removed"),
                    changed=changed,
                    count=len(products),
                )
            )
            # default taxes of new products and bills
            company.write(
                {
                    "account_sale_tax_id": sale_tax.id if registered else False,
                    "account_purchase_tax_id": purchase_tax.id if registered else False,
                    "earlydryer_vat_applied_state": company._earlydryer_vat_state(),
                }
            )
            configs = self.env["pos.config"].sudo().search(
                [("company_id", "=", company.id), ("earlydryer_enabled", "=", True)]
            )
            for config in configs:
                # POS lines take the product taxes; a default fiscal position
                # would map them, so none is forced here
                if config.tax_regime_selection and not registered:
                    config.write(
                        {"tax_regime_selection": False, "default_fiscal_position_id": False}
                    )
            if configs:
                summary.append(
                    self.env._(
                        "%(count)s POS configurations take the product taxes "
                        "(reopen their sessions to load them).",
                        count=len(configs),
                    )
                )
        return summary

    def _earlydryer_vat_state(self):
        self.ensure_one()
        return "%s/%s" % (
            int(self.earlydryer_vat_registered),
            int(self.earlydryer_prices_include_vat),
        )

    def _earlydryer_is_live(self):
        """Whether documents were already issued (VAT switch warning)."""
        self.ensure_one()
        return bool(
            self.env["account.move"]
            .sudo()
            .search_count(
                [
                    ("company_id", "=", self.id),
                    ("move_type", "in", ("out_invoice", "out_refund")),
                    ("state", "=", "posted"),
                ],
                limit=1,
            )
            or self.env["pos.order"]
            .sudo()
            .search_count([("company_id", "=", self.id)], limit=1)
        )
