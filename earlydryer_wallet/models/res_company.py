# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# proposed codes live in ir.config_parameter (data file), never in Python
ADVANCES_CODE_PARAM = "earlydryer_wallet.advances_account_code"
CREDIT_CODE_PARAM = "earlydryer_wallet.credit_account_code"
JOURNAL_CODE_PARAM = "earlydryer_wallet.journal_code"


class ResCompany(models.Model):
    _inherit = "res.company"

    earlydryer_wallet_account_id = fields.Many2one(
        "account.account",
        string="Customer Advances Account",
        check_company=True,
        help="Current liability holding the customers' prepaid wallet balances. "
        "Used for nothing else; it must allow reconciliation.",
    )
    earlydryer_wallet_journal_id = fields.Many2one(
        "account.journal",
        string="Wallet Journal",
        check_company=True,
        domain=[("type", "=", "general")],
        help="Miscellaneous journal of the wallet spends, credits and migration.",
    )
    earlydryer_wallet_credit_account_id = fields.Many2one(
        "account.account",
        string="Goodwill and Claims Account",
        check_company=True,
        help="Expense debited by goodwill and claim credits to a wallet.",
    )
    earlydryer_wallet_opening_account_id = fields.Many2one(
        "account.account",
        string="Wallet Opening Account",
        check_company=True,
        help="Debited by the migration of the old notebook balances. Defaults to "
        "the company's undistributed profits account.",
    )
    earlydryer_wallet_auto_apply = fields.Boolean(
        string="Apply Wallet to Invoices",
        help="Posting a customer invoice from a sales order or laundry job spends "
        "the customer's available wallet balance on it.",
    )
    earlydryer_wallet_min_topup = fields.Monetary(
        string="Minimum Top-up", currency_field="currency_id"
    )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _earlydryer_wallet_xmlid(self, name):
        self.ensure_one()
        return f"{self.id}_{name}"

    def _earlydryer_wallet_ref(self, name):
        self.ensure_one()
        return self.env.ref(
            f"earlydryer_wallet.{self._earlydryer_wallet_xmlid(name)}",
            raise_if_not_found=False,
        )

    def _earlydryer_wallet_bind(self, name, record):
        """XML id of a record created for this company, so it survives chart
        changes and updates."""
        self.ensure_one()
        self.env["ir.model.data"].sudo().create(
            {
                "module": "earlydryer_wallet",
                "name": self._earlydryer_wallet_xmlid(name),
                "model": record._name,
                "res_id": record.id,
                "noupdate": True,
            }
        )
        return record

    def _earlydryer_free_account_code(self, code):
        """``code`` or the next free code after it in this company's chart."""
        self.ensure_one()
        Account = self.env["account.account"].with_company(self)
        candidate = code
        while Account.search_count(
            [*Account._check_company_domain(self), ("code", "=", candidate)], limit=1
        ):
            candidate = (
                str(int(candidate) + 1) if candidate.isdigit() else candidate + "1"
            )
        return candidate

    def _earlydryer_wallet_account(self, name, label, code_param, account_type):
        self.ensure_one()
        account = self._earlydryer_wallet_ref(name)
        if account:
            return account
        params = self.env["ir.config_parameter"].sudo()
        code = self._earlydryer_free_account_code(params.get_param(code_param) or "1")
        account = (
            self.env["account.account"]
            .sudo()
            .with_company(self)
            .create(
                {
                    "name": label,
                    "code": code,
                    "account_type": account_type,
                    "reconcile": account_type == "liability_current",
                    "company_ids": [(6, 0, self.ids)],
                }
            )
        )
        _logger.info("Wallet account %s %s created for %s.", code, label, self.name)
        return self._earlydryer_wallet_bind(name, account)

    def _earlydryer_wallet_setup(self):
        """Customer advances and goodwill accounts, Wallet journal, settings,
        top-up product account and Wallet POS method, when missing.

        Companies without a chart are skipped (run again after loading one).
        """
        params = self.env["ir.config_parameter"].sudo()
        for company in self.sudo():
            if not company.chart_template:
                continue
            vals = {}
            if not company.earlydryer_wallet_account_id:
                vals["earlydryer_wallet_account_id"] = (
                    company._earlydryer_wallet_account(
                        "wallet_advances_account",
                        self.env._("Customer Advances (Wallet)"),
                        ADVANCES_CODE_PARAM,
                        "liability_current",
                    ).id
                )
            if not company.earlydryer_wallet_credit_account_id:
                vals["earlydryer_wallet_credit_account_id"] = (
                    company._earlydryer_wallet_account(
                        "wallet_credit_account",
                        self.env._("Claims and Goodwill"),
                        CREDIT_CODE_PARAM,
                        "expense",
                    ).id
                )
            if not company.earlydryer_wallet_opening_account_id:
                vals["earlydryer_wallet_opening_account_id"] = (
                    company.get_unaffected_earnings_account().id
                )
            if not company.earlydryer_wallet_journal_id:
                journal = company._earlydryer_wallet_ref("wallet_journal")
                if not journal:
                    Journal = self.env["account.journal"].sudo()
                    code = params.get_param(JOURNAL_CODE_PARAM) or "WAL"
                    while Journal.search_count(
                        [("company_id", "=", company.id), ("code", "=", code)], limit=1
                    ):
                        code = code[:4] + "X"
                    journal = Journal.create(
                        {
                            "name": self.env._("Wallet"),
                            "code": code,
                            "type": "general",
                            "company_id": company.id,
                        }
                    )
                    company._earlydryer_wallet_bind("wallet_journal", journal)
                vals["earlydryer_wallet_journal_id"] = journal.id
            if vals:
                company.write(vals)
            company._earlydryer_wallet_setup_topup_product()
            enabled = self.env["pos.config"].search_count(
                [("company_id", "=", company.id), ("earlydryer_enabled", "=", True)],
                limit=1,
            )
            if enabled:
                company._earlydryer_wallet_pos_method()
        return True

    def _earlydryer_wallet_setup_topup_product(self):
        """Top-ups sold at the till credit the customer advances, not revenue
        (the session posting also routes them per customer, see pos.session)."""
        self.ensure_one()
        product = self.env.ref(
            "earlydryer_wallet.product_wallet_topup", raise_if_not_found=False
        )
        if product and self.earlydryer_wallet_account_id:
            template = product.product_tmpl_id.sudo().with_company(self)
            if template.property_account_income_id != self.earlydryer_wallet_account_id:
                template.property_account_income_id = self.earlydryer_wallet_account_id
        return product

    def _earlydryer_wallet_pos_method(self):
        """The company's Wallet POS payment method (created when missing)."""
        self.ensure_one()
        Method = self.env["pos.payment.method"].sudo()
        method = Method.with_context(active_test=False).search(
            [("company_id", "=", self.id), ("earlydryer_is_wallet", "=", True)],
            order="active desc, id",
            limit=1,
        )
        if method:
            return method
        method = Method.create(
            {
                "name": self.env._("Wallet"),
                "company_id": self.id,
                "earlydryer_is_wallet": True,
                "split_transactions": True,
            }
        )
        if not self._earlydryer_wallet_ref("wallet_pos_method"):
            self._earlydryer_wallet_bind("wallet_pos_method", method)
        return method

    def _earlydryer_wallet_check_setup(self):
        """Raise when the wallet accounts of this company are not set."""
        self.ensure_one()
        missing = [
            self._fields[name].get_description(self.env)["string"]
            for name in ("earlydryer_wallet_account_id", "earlydryer_wallet_journal_id")
            if not self[name]
        ]
        if missing:
            raise UserError(
                self.env._(
                    "Set up the wallet of %(company)s first (Settings > Earlydryer "
                    "> Wallet): %(fields)s.",
                    company=self.name,
                    fields=", ".join(missing),
                )
            )
        return True
