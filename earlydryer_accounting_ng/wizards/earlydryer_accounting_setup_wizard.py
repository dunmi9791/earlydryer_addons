# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)
_logger = logging.getLogger(__name__)

# (key, label, code parameter, account type, reconcile, company field)
# Codes are proposals read from ir.config_parameter (PLACEHOLDERS).
COMPANY_ACCOUNTS = [
    (
        "laundry_income",
        _lt("Laundry Service Revenue"),
        "code_laundry_income",
        "income",
        False,
        "earlydryer_laundry_income_account_id",
    ),
    (
        "retail_income",
        _lt("Retail Sales Revenue"),
        "code_retail_income",
        "income",
        False,
        "earlydryer_retail_income_account_id",
    ),
    (
        "delivery_income",
        _lt("Delivery Fee Revenue"),
        "code_delivery_income",
        "income",
        False,
        "earlydryer_delivery_income_account_id",
    ),
    (
        "discount",
        _lt("Sales Discounts"),
        "code_discount",
        "income",
        False,
        "earlydryer_discount_account_id",
    ),
    (
        "retail_cogs",
        _lt("Cost of Retail Goods Sold"),
        "code_retail_cogs",
        "expense_direct_cost",
        False,
        "earlydryer_retail_cogs_account_id",
    ),
    (
        "consumables",
        _lt("Laundry Consumables"),
        "code_consumables",
        "expense_direct_cost",
        False,
        "earlydryer_consumables_account_id",
    ),
    (
        "cash_diff",
        _lt("Cash Over and Short"),
        "code_cash_diff",
        "expense",
        False,
        "earlydryer_cash_diff_account_id",
    ),
    (
        "gateway_clearing",
        _lt("Payment Gateway Clearing"),
        "code_gateway_clearing",
        "asset_current",
        True,
        "earlydryer_gateway_account_id",
    ),
    (
        "cash_transit",
        _lt("Cash in Transit to Bank"),
        "code_cash_transit",
        "asset_current",
        True,
        "earlydryer_cash_transit_account_id",
    ),
    (
        "wht_payable",
        _lt("WHT Payable"),
        "code_wht_payable",
        "liability_current",
        True,
        "earlydryer_wht_payable_account_id",
    ),
    (
        "wht_receivable",
        _lt("WHT Receivable"),
        "code_wht_receivable",
        "asset_current",
        True,
        "earlydryer_wht_receivable_account_id",
    ),
]


class EarlydryerAccountingSetupWizard(models.TransientModel):
    """Chart additions, journals, taxes, analytics, fiscal year and POS
    payment methods of Earlydryer, for the current company.

    Idempotent: records are found by XML id (``earlydryer_accounting_ng.
    <company id>_<key>``), then by code; only the missing ones are created and
    each gets its XML id, so a second run creates nothing.
    """

    _name = "earlydryer.accounting.setup.wizard"
    _description = "Earlydryer Accounting Setup"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    state = fields.Selection(
        [("config", "Options"), ("preview", "Preview"), ("done", "Done")],
        default="config",
        required=True,
    )
    bank_name = fields.Char(
        string="Bank", help="Name of a real bank account's bank, e.g. 'Example Bank'."
    )
    bank_acc_number = fields.Char(string="Account Number")
    card_providers = fields.Char(
        string="Card Terminal Providers",
        default=lambda self: self.env._("Card Terminal"),
        help="Comma-separated: one clearing account and journal per provider.",
    )
    separate_discounts = fields.Boolean(
        string="Show Discounts Separately",
        help="Create a Sales Discounts account (to confirm with the accountant).",
    )
    transfer_journal_id = fields.Many2one(
        "account.journal",
        string="Bank for Transfers at the Counter",
        domain="[('company_id', '=', company_id), ('type', '=', 'bank'), "
        "('earlydryer_role', 'in', (False, 'bank'))]",
        help="Bank transfer payment method of the tills. Default: the bank "
        "journal created now, or the first Earlydryer bank journal.",
    )
    line_ids = fields.One2many(
        "earlydryer.accounting.setup.line", "wizard_id", string="Records"
    )
    pos_line_ids = fields.One2many(
        "earlydryer.accounting.setup.pos.line",
        "wizard_id",
        string="POS Payment Methods",
    )
    created_count = fields.Integer(readonly=True)
    summary = fields.Text(readonly=True)

    # ------------------------------------------------------------------
    # Rights
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_check_setup_right(self):
        user = self.env.user
        if self.env.su or user.has_group("earlydryer_base.group_finance") or (
            user.has_group("earlydryer_base.group_admin")
        ):
            return True
        raise AccessError(
            self.env._("Only Finance or the Administrator run the accounting setup.")
        )

    @api.model_create_multi
    def create(self, vals_list):
        self._earlydryer_check_setup_right()
        return super().create(vals_list)

    @api.model
    def action_open(self):
        self._earlydryer_check_setup_right()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Accounting Setup"),
            "res_model": self._name,
            "view_mode": "form",
            "target": "new",
        }

    def _reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Accounting Setup"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _param(self, key, default=""):
        return self.company_id._earlydryer_param(key, default)

    def _providers(self):
        names = [name.strip() for name in (self.card_providers or "").split(",")]
        return [name for name in names if name]

    def _branches(self):
        return (
            self.env["earlydryer.branch"]
            .sudo()
            .search([("company_id", "=", self.company_id.id)], order="sequence, id")
        )

    def _Account(self):
        return self.env["account.account"].sudo().with_company(self.company_id)

    def _account_by_code(self, code):
        Account = self._Account()
        if not code:
            return Account
        return Account.search(
            [*Account._check_company_domain(self.company_id), ("code", "=", code)],
            limit=1,
        )

    def _journal_by_code(self, code):
        Journal = self.env["account.journal"].sudo().with_context(active_test=False)
        if not code:
            return Journal
        return Journal.search(
            [("company_id", "=", self.company_id.id), ("code", "=", code)], limit=1
        )

    def _free_account_code(self, code, taken):
        """``code``, or the next code free in the chart and not proposed yet."""
        candidate = code
        while self._account_by_code(candidate) or candidate in taken:
            candidate = (
                str(int(candidate) + 1) if candidate.isdigit() else candidate + "1"
            )
        taken.add(candidate)
        return candidate

    def _free_journal_code(self, code, taken):
        base = (code or "J")[:5].upper()
        candidate = base
        index = 1
        while self._journal_by_code(candidate) or candidate in taken:
            suffix = str(index)
            candidate = base[: 5 - len(suffix)] + suffix
            index += 1
        taken.add(candidate)
        return candidate

    @staticmethod
    def _slug(name):
        return "".join(char if char.isalnum() else "_" for char in name.lower())[:30]

    # ------------------------------------------------------------------
    # Plan (preview)
    # ------------------------------------------------------------------

    def _line(self, section, key, name, **vals):
        return {"section": section, "key": key, "name": name, **vals}

    def _account_line(self, key, name, code, account_type, reconcile, taken, **extra):
        """Line of an account: existing by XML id, by code, or to create."""
        company = self.company_id
        record = company._earlydryer_acc_ref(f"acc_{key}")
        status = "reuse"
        if not record:
            record = self._account_by_code(code)
        if not record:
            status = "create"
            code = self._free_account_code(code, taken)
        return self._line(
            "account",
            f"acc_{key}",
            record.name if record else name,
            code=record.code if record else code,
            account_type=record.account_type if record else account_type,
            reconcile=record.reconcile if record else reconcile,
            status=status,
            res_model="account.account" if record else False,
            res_id=record.id if record else 0,
            editable=not record,
            **extra,
        )

    def _reuse_line(self, section, key, record, note=None, **extra):
        return self._line(
            section,
            key,
            record.display_name,
            status="reuse",
            res_model=record._name,
            res_id=record.id,
            editable=False,
            note=note,
            **extra,
        )

    def _journal_line(self, key, name, code, journal_type, taken, existing=None, **extra):
        company = self.company_id
        record = existing or company._earlydryer_acc_ref(f"jnl_{key}")
        if not record:
            record = self._journal_by_code(code)
        if record:
            return self._line(
                "journal",
                f"jnl_{key}",
                record.name,
                code=record.code,
                account_type=journal_type,
                status="reuse",
                res_model="account.journal",
                res_id=record.id,
                editable=False,
                **extra,
            )
        return self._line(
            "journal",
            f"jnl_{key}",
            name,
            code=self._free_journal_code(code, taken),
            account_type=journal_type,
            status="create",
            **extra,
        )

    def _earlydryer_plan(self):
        """Values of the preview lines."""
        self.ensure_one()
        company = self.company_id
        if not company.chart_template:
            raise UserError(
                self.env._(
                    "%(company)s has no chart of accounts yet: install one first "
                    "(Nigeria: l10n_ng).",
                    company=company.name,
                )
            )
        lines = []
        taken_accounts = set()
        taken_journals = set()
        # --- company accounts
        for key, label, param, account_type, reconcile, field in COMPANY_ACCOUNTS:
            if key == "discount" and not self.separate_discounts and not company[field]:
                continue
            existing = company[field]
            if existing:
                lines.append(self._reuse_line("account", f"acc_{key}", existing))
                continue
            lines.append(
                self._account_line(
                    key,
                    str(label),
                    self._param(param),
                    account_type,
                    reconcile,
                    taken_accounts,
                )
            )
        # claims: the wallet's goodwill account
        claims = company.earlydryer_wallet_credit_account_id
        if claims:
            lines.append(
                self._reuse_line(
                    "account", "acc_claims", claims, note=self.env._("earlydryer_wallet")
                )
            )
        else:
            lines.append(
                self._account_line(
                    "claims",
                    self.env._("Claims and Goodwill"),
                    self._param("code_claims"),
                    "expense",
                    False,
                    taken_accounts,
                )
            )
        advances = company.earlydryer_wallet_account_id
        if advances:
            lines.append(
                self._reuse_line(
                    "account",
                    "acc_advances",
                    advances,
                    note=self.env._("earlydryer_wallet: never duplicated"),
                )
            )
        for tax_use, key in (("sale", "vat_output"), ("purchase", "vat_input")):
            account = company._earlydryer_default_vat_account(tax_use)
            if account:
                lines.append(self._reuse_line("account", f"acc_{key}", account))
        opening = company.earlydryer_opening_equity_account_id or (
            company.get_unaffected_earnings_account()
        )
        lines.append(
            self._reuse_line(
                "account",
                "acc_opening_equity",
                opening,
                note=self.env._("company's undistributed profits account"),
            )
        )
        # --- per plant
        cash_base = self._param("code_plant_cash") or (
            (company.cash_account_code_prefix or "") + "01"
        )
        rider_base = self._param("code_rider_cash")
        for branch in self._branches():
            journal = branch.cash_journal_id
            if journal and journal.default_account_id:
                lines.append(
                    self._reuse_line(
                        "account",
                        f"acc_plant_cash_{branch.id}",
                        journal.default_account_id,
                        branch_id=branch.id,
                    )
                )
            else:
                lines.append(
                    self._account_line(
                        f"plant_cash_{branch.id}",
                        self.env._("Cash at %(plant)s", plant=branch.name),
                        cash_base,
                        "asset_cash",
                        False,
                        taken_accounts,
                        branch_id=branch.id,
                    )
                )
            rider = branch.earlydryer_rider_journal_id
            if rider and rider.default_account_id:
                lines.append(
                    self._reuse_line(
                        "account",
                        f"acc_rider_cash_{branch.id}",
                        rider.default_account_id,
                        branch_id=branch.id,
                    )
                )
            else:
                lines.append(
                    self._account_line(
                        f"rider_cash_{branch.id}",
                        self.env._("Rider Cash in Transit %(plant)s", plant=branch.name),
                        rider_base,
                        "asset_current",
                        True,
                        taken_accounts,
                        branch_id=branch.id,
                    )
                )
            lines.append(
                self._journal_line(
                    f"plant_cash_{branch.id}",
                    self.env._("%(code)s Cash", code=branch.code),
                    "C" + branch.code,
                    "cash",
                    taken_journals,
                    existing=journal,
                    branch_id=branch.id,
                )
            )
            lines.append(
                self._journal_line(
                    f"rider_cash_{branch.id}",
                    self.env._("%(code)s Rider Cash", code=branch.code),
                    "R" + branch.code,
                    "cash",
                    taken_journals,
                    existing=branch.earlydryer_rider_journal_id,
                    branch_id=branch.id,
                )
            )
        # --- card providers (existing card journals are kept)
        Journal = self.env["account.journal"].sudo()
        card_journals = Journal.search(
            [("company_id", "=", company.id), ("earlydryer_role", "=", "card")]
        )
        for journal in card_journals:
            lines.append(
                self._reuse_line("journal", f"jnl_card_{journal.id}", journal)
            )
        known = {self._slug(name) for name in card_journals.mapped("name")}
        card_base = self._param("code_card_clearing")
        for provider in self._providers():
            slug = self._slug(provider)
            if company._earlydryer_acc_ref(f"jnl_card_{slug}") or any(
                slug in name for name in known
            ):
                continue
            lines.append(
                self._account_line(
                    f"card_{slug}",
                    self.env._("Card Clearing %(provider)s", provider=provider),
                    card_base,
                    "asset_current",
                    True,
                    taken_accounts,
                )
            )
            lines.append(
                self._journal_line(
                    f"card_{slug}",
                    self.env._("Card Clearing %(provider)s", provider=provider),
                    self._param("journal_code_card", "CRD"),
                    "bank",
                    taken_journals,
                )
            )
        # --- banks
        bank_journals = Journal.search(
            [("company_id", "=", company.id), ("earlydryer_role", "=", "bank")]
        )
        for journal in bank_journals:
            lines.append(self._reuse_line("journal", f"jnl_bank_{journal.id}", journal))
        if self.bank_name and self.bank_acc_number:
            slug = self._slug(f"{self.bank_name}_{self.bank_acc_number}")
            lines.append(
                self._journal_line(
                    f"bank_{slug}",
                    f"{self.bank_name} {self.bank_acc_number}",
                    self._param("journal_code_bank", "BNK"),
                    "bank",
                    taken_journals,
                    existing=Journal.search(
                        [
                            ("company_id", "=", company.id),
                            ("bank_acc_number", "=", self.bank_acc_number),
                        ],
                        limit=1,
                    ),
                )
            )
        elif not bank_journals:
            lines.append(
                self._line(
                    "journal",
                    "jnl_bank_missing",
                    self.env._("Bank account"),
                    status="skip",
                    editable=False,
                    note=self.env._(
                        "Give the bank and account number to create the bank journal."
                    ),
                )
            )
        lines.append(
            self._journal_line(
                "gateway",
                self.env._("Payment Gateway Clearing"),
                self._param("journal_code_gateway", "PGW"),
                "bank",
                taken_journals,
                existing=company.earlydryer_gateway_journal_id,
            )
        )
        lines.append(
            self._journal_line(
                "opening",
                self.env._("Opening Balances"),
                self._param("journal_code_opening", "OPEN"),
                "general",
                taken_journals,
                existing=company.earlydryer_opening_journal_id,
            )
        )
        if company.earlydryer_wallet_journal_id:
            lines.append(
                self._reuse_line(
                    "journal",
                    "jnl_wallet",
                    company.earlydryer_wallet_journal_id,
                    note=self.env._("earlydryer_wallet"),
                )
            )
        # --- the other steps (not editable)
        lines += [
            self._line(
                "tax",
                "tax_vat",
                self.env._("VAT 7.5% on sales and purchases"),
                status="reuse" if company.earlydryer_sale_tax_id else "create",
                editable=False,
                note=self.env._("l10n_ng taxes when the company uses the Nigerian chart"),
            ),
            self._line(
                "tax",
                "tax_vat_apply",
                self.env._("Apply the VAT setting (registered: %(state)s)", state=self.env._("yes") if company.earlydryer_vat_registered else self.env._("no")),
                status="create",
                editable=False,
            ),
            self._line(
                "tax",
                "tax_wht",
                self.env._("WHT taxes of the active WHT categories"),
                status="create",
                editable=False,
            ),
            self._line(
                "analytic",
                "analytic_plants",
                self.env._("Plant analytic accounts and distribution models"),
                status="create",
                editable=False,
            ),
            self._line(
                "analytic",
                "analytic_service_lines",
                self.env._("Service line distribution models"),
                status="create",
                editable=False,
            ),
            self._line(
                "fiscal",
                "fiscal_year",
                self.env._(
                    "Fiscal year ending 31 December, fiscal years %(y1)s and %(y2)s, "
                    "monthly periods",
                    y1=fields.Date.context_today(self).year,
                    y2=fields.Date.context_today(self).year + 1,
                ),
                status="create",
                editable=False,
            ),
            self._line(
                "report",
                "mis_instances",
                self.env._("P&L by plant, P&L by service line, cash flow summary"),
                status="create",
                editable=False,
            ),
        ]
        for sequence, vals in enumerate(lines, start=1):
            vals["sequence"] = sequence
        return lines

    def action_preview(self):
        self.ensure_one()
        self._earlydryer_check_setup_right()
        self.line_ids.unlink()
        self.write(
            {
                "line_ids": [Command.create(vals) for vals in self._earlydryer_plan()],
                "state": "preview",
            }
        )
        return self._reopen()

    def action_back(self):
        self.write({"state": "config"})
        return self._reopen()

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def action_apply(self):
        self.ensure_one()
        self._earlydryer_check_setup_right()
        if self.state != "preview":
            self.action_preview()
        summary = self.sudo()._earlydryer_apply()
        self.write({"state": "done", "summary": "\n".join(summary)})
        return self._reopen()

    def _earlydryer_run(self):
        """Preview and apply in one go (demo data, tests, scripts)."""
        self.ensure_one()
        self.action_preview()
        return self.action_apply()

    def _lines_by_key(self):
        return {line.key: line for line in self.line_ids}

    def _apply_account(self, line):
        company = self.company_id
        if line.status == "reuse":
            record = line._record()
            if record and not company._earlydryer_acc_ref(line.key) and line.key not in (
                "acc_advances",
                "acc_claims",
                "acc_opening_equity",
                "acc_vat_output",
                "acc_vat_input",
            ):
                company._earlydryer_acc_bind(line.key, record)
            return record
        if line.status != "create":
            return self._Account()
        existing = company._earlydryer_acc_ref(line.key) or self._account_by_code(
            line.code
        )
        if existing:
            company._earlydryer_acc_bind(line.key, existing)
            line.write({"status": "reuse", "res_model": existing._name, "res_id": existing.id})
            return existing
        account = self._Account().create(
            {
                "name": line.name,
                "code": line.code,
                "account_type": line.account_type,
                "reconcile": line.reconcile,
                "company_ids": [Command.set(company.ids)],
            }
        )
        company._earlydryer_acc_bind(line.key, account)
        line.write({"status": "done", "res_model": account._name, "res_id": account.id})
        _logger.info("Account %s %s created for %s.", account.code, account.name, company.name)
        return account

    def _apply_journal(self, line, vals):
        company = self.company_id
        Journal = self.env["account.journal"].sudo()
        if line.status == "reuse":
            journal = line._record()
            if journal and line.key.startswith(("jnl_plant_", "jnl_rider_", "jnl_gateway", "jnl_opening")) and not company._earlydryer_acc_ref(line.key):
                company._earlydryer_acc_bind(line.key, journal)
            if journal and vals.get("earlydryer_role") and not journal.earlydryer_role:
                journal.earlydryer_role = vals["earlydryer_role"]
            return journal
        if line.status != "create":
            return Journal
        journal = company._earlydryer_acc_ref(line.key) or self._journal_by_code(line.code)
        if journal:
            company._earlydryer_acc_bind(line.key, journal)
            return journal
        journal = Journal.create(
            {
                "name": line.name,
                "code": line.code,
                "company_id": company.id,
                **vals,
            }
        )
        company._earlydryer_acc_bind(line.key, journal)
        line.write({"status": "done", "res_model": journal._name, "res_id": journal.id})
        return journal

    def _set_inbound_account(self, journal, account):
        """Outstanding receipts of a clearing journal go to its clearing account."""
        for method_line in journal.inbound_payment_method_line_ids:
            if not method_line.payment_account_id:
                method_line.payment_account_id = account

    def _earlydryer_apply(self):
        self.ensure_one()
        company = self.company_id
        lines = self._lines_by_key()
        summary = []
        created_before = len(self.line_ids.filtered(lambda line: line.status == "done"))

        # accounts
        accounts = {}
        for line in self.line_ids.filtered(lambda line: line.section == "account"):
            accounts[line.key] = self._apply_account(line)
        company_vals = {}
        for key, _label, _param, _type, _reconcile, field in COMPANY_ACCOUNTS:
            account = accounts.get(f"acc_{key}")
            if account and company[field] != account:
                company_vals[field] = account.id
        if not company.earlydryer_wallet_credit_account_id and accounts.get("acc_claims"):
            company_vals["earlydryer_wallet_credit_account_id"] = accounts["acc_claims"].id
        if not company.earlydryer_opening_equity_account_id:
            company_vals["earlydryer_opening_equity_account_id"] = accounts[
                "acc_opening_equity"
            ].id
        if company_vals:
            company.write(company_vals)
        cash_diff = company.earlydryer_cash_diff_account_id

        # plant and rider cash journals
        for branch in self._branches():
            cash_line = lines.get(f"jnl_plant_cash_{branch.id}")
            if cash_line:
                journal = self._apply_journal(
                    cash_line,
                    {
                        "type": "cash",
                        "default_account_id": accounts[f"acc_plant_cash_{branch.id}"].id,
                        "earlydryer_branch_id": branch.id,
                        "earlydryer_role": "plant_cash",
                        "profit_account_id": cash_diff.id,
                        "loss_account_id": cash_diff.id,
                    },
                )
                journal_vals = {"earlydryer_role": "plant_cash"}
                if cash_diff:
                    journal_vals.update(
                        profit_account_id=cash_diff.id, loss_account_id=cash_diff.id
                    )
                if not journal.earlydryer_branch_id:
                    journal_vals["earlydryer_branch_id"] = branch.id
                journal.write(journal_vals)
                if branch.cash_journal_id != journal:
                    branch.cash_journal_id = journal
            rider_line = lines.get(f"jnl_rider_cash_{branch.id}")
            if rider_line:
                journal = self._apply_journal(
                    rider_line,
                    {
                        "type": "cash",
                        "default_account_id": accounts[f"acc_rider_cash_{branch.id}"].id,
                        "earlydryer_branch_id": branch.id,
                        "earlydryer_role": "rider_cash",
                    },
                )
                if not journal.earlydryer_branch_id:
                    journal.earlydryer_branch_id = branch
                if branch.earlydryer_rider_journal_id != journal:
                    branch.earlydryer_rider_journal_id = journal
        # card providers
        for line in self.line_ids.filtered(
            lambda line: line.key.startswith("jnl_card_")
        ):
            slug = line.key[len("jnl_card_") :]
            account = accounts.get(f"acc_card_{slug}")
            journal = self._apply_journal(
                line,
                {
                    "type": "bank",
                    "default_account_id": account.id if account else False,
                    "earlydryer_role": "card",
                },
            )
            if journal and journal.default_account_id:
                self._set_inbound_account(journal, journal.default_account_id)
        # banks
        bank_created = self.env["account.journal"]
        for line in self.line_ids.filtered(
            lambda line: line.key.startswith("jnl_bank_") and line.status != "skip"
        ):
            vals = {"type": "bank", "earlydryer_role": "bank"}
            if line.status == "create":
                vals.update(
                    bank_acc_number=self.bank_acc_number,
                    earlydryer_show_on_invoice=True,
                )
                bank = self.env["res.bank"].sudo().search(
                    [("name", "=", self.bank_name)], limit=1
                ) or self.env["res.bank"].sudo().create({"name": self.bank_name})
                vals["bank_id"] = bank.id
            journal = self._apply_journal(line, vals)
            if line.status == "done":
                bank_created |= journal
        # gateway and opening journals
        gateway_line = lines.get("jnl_gateway")
        gateway = self._apply_journal(
            gateway_line,
            {
                "type": "bank",
                "default_account_id": company.earlydryer_gateway_account_id.id,
                "earlydryer_role": "gateway",
            },
        )
        if gateway.default_account_id:
            self._set_inbound_account(gateway, gateway.default_account_id)
        opening = self._apply_journal(
            lines.get("jnl_opening"), {"type": "general", "earlydryer_role": "opening"}
        )
        company.write(
            {
                "earlydryer_gateway_journal_id": gateway.id,
                "earlydryer_opening_journal_id": opening.id,
            }
        )
        # delivery category
        self._earlydryer_setup_categories()
        # taxes
        company._earlydryer_ensure_vat_taxes()
        summary += company._earlydryer_apply_vat_setting()
        self.env["earlydryer.wht.category"].sudo().with_context(
            active_test=False
        ).search([])._earlydryer_sync_taxes(company)
        if not company.earlydryer_tax_authority_id:
            company.earlydryer_tax_authority_id = self._earlydryer_tax_authority()
        # analytics, fiscal year, reports, POS
        summary += self._earlydryer_setup_analytics()
        summary += self._earlydryer_setup_fiscal_year()
        summary += self._earlydryer_setup_mis()
        transfer = self.transfer_journal_id or bank_created[:1] or self.env[
            "account.journal"
        ].sudo().search(
            [("company_id", "=", company.id), ("earlydryer_role", "=", "bank")], limit=1
        )
        summary += self._earlydryer_setup_pos(transfer)
        created = len(self.line_ids.filtered(lambda line: line.status == "done")) - (
            created_before
        )
        self.created_count = created
        summary.insert(
            0,
            self.env._(
                "%(count)s account(s) and journal(s) created, the others reused.",
                count=created,
            ),
        )
        return summary

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _earlydryer_tax_authority(self):
        partner = self.env.ref(
            "earlydryer_accounting_ng.partner_tax_authority", raise_if_not_found=False
        )
        return partner.id if partner else False

    def _earlydryer_setup_categories(self):
        company = self.company_id
        category = self.env.ref(
            "earlydryer_accounting_ng.product_category_delivery",
            raise_if_not_found=False,
        )
        account = company.earlydryer_delivery_income_account_id
        if category and account:
            category = category.sudo().with_company(company)
            if category.property_account_income_categ_id != account:
                category.property_account_income_categ_id = account

    def _earlydryer_setup_analytics(self):
        """Plant accounts in the Plants plan, one distribution model per plant
        and per service line."""
        company = self.company_id
        summary = []
        AnalyticAccount = self.env["account.analytic.account"].sudo()
        Model = self.env["account.analytic.distribution.model"].sudo()
        plan = self.env.ref("earlydryer_accounting_ng.analytic_plan_plants")
        moved = created = 0
        for branch in self._branches():
            account = branch.analytic_account_id
            if account and account.plan_id != plan:
                account.plan_id = plan
                moved += 1
            if not account:
                account = company._earlydryer_acc_ref(
                    f"analytic_plant_{branch.id}"
                ) or AnalyticAccount.create(
                    {
                        "name": branch.name,
                        "code": branch.code,
                        "plan_id": plan.id,
                        "company_id": company.id,
                    }
                )
                company._earlydryer_acc_bind(f"analytic_plant_{branch.id}", account)
                branch.analytic_account_id = account
                created += 1
            key = f"distribution_plant_{branch.id}"
            model = company._earlydryer_acc_ref(key)
            if not model:
                model = Model.create(
                    {
                        "earlydryer_branch_id": branch.id,
                        "company_id": company.id,
                        "analytic_distribution": {str(account.id): 100.0},
                        "sequence": 50,
                    }
                )
                company._earlydryer_acc_bind(key, model)
            elif model.analytic_distribution != {str(account.id): 100.0}:
                model.analytic_distribution = {str(account.id): 100.0}
        service_plan = self.env.ref(
            "earlydryer_accounting_ng.analytic_plan_service_lines"
        )
        service_lines = AnalyticAccount.search([("plan_id", "=", service_plan.id)])
        for service_line in service_lines:
            key = f"distribution_service_line_{service_line.id}"
            if company._earlydryer_acc_ref(key):
                continue
            model = Model.create(
                {
                    "earlydryer_service_line_id": service_line.id,
                    "company_id": company.id,
                    "analytic_distribution": {str(service_line.id): 100.0},
                    "sequence": 60,
                }
            )
            company._earlydryer_acc_bind(key, model)
        summary.append(
            self.env._(
                "Analytics: %(created)s plant account(s) created, %(moved)s moved to "
                "the Plants plan, %(lines)s service lines.",
                created=created,
                moved=moved,
                lines=len(service_lines),
            )
        )
        return summary

    def _earlydryer_setup_fiscal_year(self):
        company = self.company_id
        summary = []
        if company.fiscalyear_last_month != "12" or company.fiscalyear_last_day != 31:
            company.write({"fiscalyear_last_month": "12", "fiscalyear_last_day": 31})
        FiscalYear = self.env["account.fiscal.year"].sudo()
        year = fields.Date.context_today(self).year
        for current in (year, year + 1):
            start, end = date(current, 1, 1), date(current, 12, 31)
            overlap = FiscalYear.search(
                [
                    ("company_id", "=", company.id),
                    ("date_from", "<=", end),
                    ("date_to", ">=", start),
                ],
                limit=1,
            )
            if not overlap:
                FiscalYear.create(
                    {
                        "name": str(current),
                        "date_from": start,
                        "date_to": end,
                        "company_id": company.id,
                    }
                )
                summary.append(self.env._("Fiscal year %(year)s created.", year=current))
        RangeType = self.env["date.range.type"].sudo()
        range_type = company._earlydryer_acc_ref("date_range_type_month")
        if not range_type:
            range_type = RangeType.create(
                {
                    "name": self.env._("Earlydryer Monthly Periods"),
                    "company_id": company.id,
                    "allow_overlap": False,
                    "earlydryer_period_type": True,
                }
            )
            company._earlydryer_acc_bind("date_range_type_month", range_type)
        Range = self.env["date.range"].sudo()
        new = 0
        for month in range(24):
            start = date(year, 1, 1) + relativedelta(months=month)
            end = start + relativedelta(months=1, days=-1)
            if Range.search_count(
                [("type_id", "=", range_type.id), ("date_start", "=", start)], limit=1
            ):
                continue
            Range.create(
                {
                    "name": start.strftime("%Y-%m"),
                    "date_start": start,
                    "date_end": end,
                    "type_id": range_type.id,
                    "company_id": company.id,
                }
            )
            new += 1
        if new:
            summary.append(self.env._("%(count)s monthly periods created.", count=new))
        return summary

    def _earlydryer_setup_mis(self):
        """P&L instances with one column per plant / service line, plus the
        cash flow summary."""
        company = self.company_id
        Instance = self.env["mis.report.instance"].sudo()
        summary = []
        pnl = self.env.ref("earlydryer_accounting_ng.mis_report_pnl")
        cash = self.env.ref("earlydryer_accounting_ng.mis_report_cash_flow")
        plants = self._branches().analytic_account_id
        service_plan = self.env.ref(
            "earlydryer_accounting_ng.analytic_plan_service_lines"
        )
        service_lines = self.env["account.analytic.account"].sudo().search(
            [("plan_id", "=", service_plan.id)]
        )
        for key, name, report, columns in (
            ("mis_pnl_plant", self.env._("P&L by Plant"), pnl, plants),
            ("mis_pnl_service_line", self.env._("P&L by Service Line"), pnl, service_lines),
            ("mis_cash_flow", self.env._("Cash Flow Summary"), cash, None),
        ):
            instance = company._earlydryer_acc_ref(key)
            if not instance:
                instance = Instance.create(
                    {"name": name, "report_id": report.id, "company_id": company.id}
                )
                company._earlydryer_acc_bind(key, instance)
                summary.append(self.env._("Report %(name)s created.", name=name))
            periods = instance.period_ids
            sequence = 10
            for column in columns or []:
                domain = f"[('analytic_distribution', 'in', [{column.id}])]"
                if not periods.filtered(lambda p, domain=domain: p.analytic_domain == domain):
                    instance.period_ids = [
                        Command.create(
                            {
                                "name": column.name,
                                "mode": "relative",
                                "type": "m",
                                "offset": 0,
                                "duration": 1,
                                "source": "actuals",
                                "analytic_domain": domain,
                                "sequence": sequence,
                            }
                        )
                    ]
                sequence += 10
            if not instance.period_ids.filtered(
                lambda p: p.analytic_domain in (False, "[]")
            ):
                instance.period_ids = [
                    Command.create(
                        {
                            "name": self.env._("Total"),
                            "mode": "relative",
                            "type": "m",
                            "offset": 0,
                            "duration": 1,
                            "source": "actuals",
                            "sequence": 900,
                        }
                    )
                ]
        return summary

    def _earlydryer_setup_pos(self, transfer_journal):
        """Cash, card and bank transfer methods of each Earlydryer till.
        Customer account and wallet methods are left as their modules made them;
        a method used in a session is never deleted."""
        company = self.company_id
        Method = self.env["pos.payment.method"].sudo()
        configs = self.env["pos.config"].sudo().search(
            [("company_id", "=", company.id), ("earlydryer_enabled", "=", True)]
        )
        card_journal = self.env["account.journal"].sudo().search(
            [("company_id", "=", company.id), ("earlydryer_role", "=", "card")],
            order="id",
            limit=1,
        )
        pos_lines = []
        summary = []
        for config in configs:
            branch = config.earlydryer_branch_id
            wanted = [
                ("cash", self.env._("Cash"), branch.cash_journal_id),
                ("card", self.env._("Card"), card_journal),
                ("transfer", self.env._("Bank Transfer"), transfer_journal),
            ]
            if config.current_session_id:
                for kind, label, journal in wanted:
                    pos_lines.append(
                        {
                            "config_id": config.id,
                            "kind": label,
                            "journal_id": journal.id or False,
                            "action": self.env._("skipped: session open"),
                        }
                    )
                continue
            methods = config.payment_method_ids
            for sequence, (kind, label, journal) in enumerate(wanted):
                if not journal:
                    pos_lines.append(
                        {
                            "config_id": config.id,
                            "kind": label,
                            "sequence": sequence,
                            "action": self.env._("skipped: no journal"),
                        }
                    )
                    continue
                method = methods.filtered(lambda m, journal=journal: m.journal_id == journal)[:1]
                action = self.env._("kept")
                if not method:
                    method = Method.search(
                        [
                            ("company_id", "=", company.id),
                            ("journal_id", "=", journal.id),
                            ("split_transactions", "=", False),
                        ],
                        limit=1,
                    )
                    action = self.env._("linked")
                if not method:
                    method = Method.create(
                        {
                            "name": f"{label} {branch.code}" if kind == "cash" else label,
                            "journal_id": journal.id,
                            "company_id": company.id,
                        }
                    )
                    action = self.env._("created")
                if kind == "card" and journal.default_account_id and (
                    method.outstanding_account_id != journal.default_account_id
                ):
                    method.outstanding_account_id = journal.default_account_id
                # the method this one replaces on the till (same kind, other
                # journal) is unlinked from the till, never deleted
                replaced = methods.filtered(
                    lambda m, kind=kind, journal=journal: m.journal_id
                    and m.journal_id != journal
                    and m.type == ("cash" if kind == "cash" else "bank")
                    and self._earlydryer_method_kind(m) == kind
                )
                commands = [Command.link(method.id)] + [
                    Command.unlink(old.id) for old in replaced
                ]
                if method not in methods or replaced:
                    config.payment_method_ids = commands
                    if replaced:
                        action += self.env._(
                            " (replaces %(old)s)", old=", ".join(replaced.mapped("name"))
                        )
                pos_lines.append(
                    {
                        "config_id": config.id,
                        "kind": label,
                        "sequence": sequence,
                        "method_id": method.id,
                        "journal_id": journal.id,
                        "action": action,
                    }
                )
            for method in config.payment_method_ids.filtered(lambda m: not m.journal_id):
                pos_lines.append(
                    {
                        "config_id": config.id,
                        "kind": self.env._("Wallet")
                        if method.earlydryer_is_wallet
                        else self.env._("Customer Account"),
                        "sequence": 10,
                        "method_id": method.id,
                        "action": self.env._("left as is"),
                    }
                )
        self.pos_line_ids.unlink()
        self.pos_line_ids = [Command.create(vals) for vals in pos_lines]
        summary.append(
            self.env._("%(count)s till(s) checked.", count=len(configs))
        )
        return summary

    @api.model
    def _earlydryer_method_kind(self, method):
        journal = method.journal_id
        if not journal:
            return False
        if journal.type == "cash":
            return "cash"
        if journal.earlydryer_role == "card" or method.use_payment_terminal:
            return "card"
        if journal.earlydryer_role == "bank":
            return "transfer"
        name = (method.name or "").lower()
        if "card" in name:
            return "card"
        if "transfer" in name or "bank" in name:
            return "transfer"
        return False
