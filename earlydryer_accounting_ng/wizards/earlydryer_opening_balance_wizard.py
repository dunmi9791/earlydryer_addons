# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import csv
import hashlib
import io
from datetime import date, datetime

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command

from odoo.addons.earlydryer_wallet.tools import normalize_ng_phone

COLUMNS = ("account_code", "account_name", "debit", "credit")
OPTIONAL_COLUMNS = ("partner_ref", "plant_code", "label", "date_maturity")


class EarlydryerOpeningBalanceWizard(models.TransientModel):
    """Opening trial balance at the cut-over date: dry run first, then one
    entry in the Opening balances journal."""

    _name = "earlydryer.opening.balance.wizard"
    _description = "Import Opening Balances"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date(string="Cut-over Date", required=True)
    file = fields.Binary(required=True, attachment=False)
    filename = fields.Char()
    state = fields.Selection(
        [("upload", "Upload"), ("preview", "Preview"), ("done", "Done")],
        default="upload",
        required=True,
    )
    line_ids = fields.One2many(
        "earlydryer.opening.balance.line", "wizard_id", string="Rows"
    )
    total_debit = fields.Monetary(compute="_compute_totals")
    total_credit = fields.Monetary(compute="_compute_totals")
    difference = fields.Monetary(
        compute="_compute_totals",
        help="Debits minus credits. Booked on Opening balance equity only when "
        "confirmed.",
    )
    error_count = fields.Integer(compute="_compute_totals", string="Errors")
    advances_tb_amount = fields.Monetary(
        compute="_compute_totals",
        string="Customer Advances in the File",
        help="Credit balance of the Customer advances rows of the file (refused: "
        "wallet balances come in through the wallet import).",
    )
    advances_wallet_amount = fields.Monetary(
        compute="_compute_totals",
        string="Wallet Import Total",
        help="Balances posted by the wallet import (earlydryer_wallet).",
    )
    confirm_difference = fields.Boolean(
        string="Book the Difference on Opening Balance Equity"
    )
    move_id = fields.Many2one("account.move", string="Opening Entry", readonly=True)

    @api.depends("line_ids.debit", "line_ids.credit", "line_ids.status")
    def _compute_totals(self):
        for wizard in self:
            lines = wizard.line_ids
            valid = lines.filtered(lambda line: line.status != "advances")
            wizard.total_debit = sum(valid.mapped("debit"))
            wizard.total_credit = sum(valid.mapped("credit"))
            wizard.difference = wizard.currency_id.round(
                wizard.total_debit - wizard.total_credit
            ) if wizard.currency_id else 0.0
            wizard.error_count = len(lines.filtered(lambda line: line.status != "ok"))
            advances = lines.filtered(lambda line: line.status == "advances")
            wizard.advances_tb_amount = sum(advances.mapped("credit")) - sum(
                advances.mapped("debit")
            )
            wizard.advances_wallet_amount = sum(
                self.env["earlydryer.wallet.transaction"]
                .sudo()
                .search(
                    [
                        ("company_id", "=", wizard.company_id.id),
                        ("source", "=", "import"),
                        ("state", "=", "posted"),
                    ]
                )
                .mapped("signed_amount")
            )

    @api.model
    def _earlydryer_check_right(self):
        user = self.env.user
        if self.env.su or user.has_group("earlydryer_base.group_finance") or (
            user.has_group("earlydryer_base.group_admin")
        ):
            return True
        raise AccessError(
            self.env._("Only Finance or the Administrator import opening balances.")
        )

    @api.model_create_multi
    def create(self, vals_list):
        self._earlydryer_check_right()
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # File
    # ------------------------------------------------------------------

    def _file_hash(self):
        self.ensure_one()
        return hashlib.sha256(base64.b64decode(self.file or b"")).hexdigest()

    def _read_rows(self):
        """Rows of the CSV or XLSX file as dicts (lower-case headers)."""
        self.ensure_one()
        content = base64.b64decode(self.file or b"")
        name = (self.filename or "").lower()
        if name.endswith(".xlsx"):
            import openpyxl  # pylint: disable=import-outside-toplevel

            workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            values = list(workbook.active.iter_rows(values_only=True))
            if not values:
                return []
            headers = [str(header or "").strip().lower() for header in values[0]]
            rows = [dict(zip(headers, row, strict=False)) for row in values[1:]]
        else:
            text = content.decode("utf-8-sig")
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
            reader = csv.DictReader(io.StringIO(text), dialect=dialect)
            rows = [
                {(key or "").strip().lower(): value for key, value in row.items()}
                for row in reader
            ]
        missing = [
            column for column in COLUMNS if rows and column not in rows[0]
        ]
        if missing:
            raise UserError(
                self.env._(
                    "Missing column(s): %(columns)s. Expected: %(expected)s.",
                    columns=", ".join(missing),
                    expected=", ".join(COLUMNS + OPTIONAL_COLUMNS),
                )
            )
        return [
            row
            for row in rows
            if any(value not in (None, "") for value in row.values())
        ]

    @api.model
    def _parse_amount(self, value):
        if isinstance(value, int | float):
            return float(value)
        text = str(value or "").replace(",", "").replace("₦", "").strip()
        if not text:
            return 0.0
        if text.startswith("(") and text.endswith(")"):
            text = f"-{text[1:-1]}"
        return float(text)

    @api.model
    def _parse_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValueError(text)

    def _match_partner(self, ref):
        """Partner by normalised Nigerian phone, then ``ref``, then exact name."""
        Partner = self.env["res.partner"].sudo().with_context(active_test=False)
        ref = str(ref or "").strip()
        if not ref:
            return Partner
        phone = normalize_ng_phone(ref)
        if phone.startswith("+234") and len(phone) == 14:
            for partner in Partner.search([("phone", "ilike", phone[-9:])], order="id"):
                if normalize_ng_phone(partner.phone) == phone:
                    return partner.commercial_partner_id
        partner = Partner.search([("ref", "=", ref)], order="id", limit=1)
        if not partner:
            partner = Partner.search([("name", "=", ref)], order="id", limit=1)
        return partner.commercial_partner_id

    def _preview_vals(self):
        self.ensure_one()
        company = self.company_id
        Account = self.env["account.account"].sudo().with_company(company)
        advances = company.earlydryer_wallet_account_id
        branches = self.env["earlydryer.branch"].sudo().search(
            [("company_id", "=", company.id)]
        )
        vals_list = []
        for number, row in enumerate(self._read_rows(), start=2):
            code = str(row.get("account_code") or "").strip()
            if code.endswith(".0"):
                code = code[:-2]
            vals = {
                "row": number,
                "account_code": code,
                "account_name": str(row.get("account_name") or "").strip(),
                "partner_ref": str(row.get("partner_ref") or "").strip(),
                "plant_code": str(row.get("plant_code") or "").strip().upper(),
                "label": str(row.get("label") or "").strip(),
                "status": "ok",
            }
            messages = []
            try:
                vals["debit"] = self._parse_amount(row.get("debit"))
                vals["credit"] = self._parse_amount(row.get("credit"))
            except ValueError:
                vals.update(debit=0.0, credit=0.0)
                messages.append(self.env._("Unreadable amount."))
            try:
                vals["date_maturity"] = self._parse_date(row.get("date_maturity"))
            except ValueError:
                messages.append(self.env._("Unreadable due date."))
            account = Account.search(
                [*Account._check_company_domain(company), ("code", "=", code)], limit=1
            )
            if not account:
                vals["status"] = "account"
                messages.append(self.env._("Unknown account %(code)s.", code=code))
            else:
                vals["account_id"] = account.id
                if vals["account_name"] and vals["account_name"].lower() != (
                    account.name or ""
                ).lower():
                    messages.append(
                        self.env._(
                            "Name differs from the chart (%(name)s): check only.",
                            name=account.name,
                        )
                    )
            if account and account == advances:
                vals["status"] = "advances"
                messages.append(
                    self.env._(
                        "Customer advances: refused. Wallet balances come in "
                        "through the wallet import."
                    )
                )
            elif account and account.account_type in (
                "asset_receivable",
                "liability_payable",
            ):
                partner = self._match_partner(vals["partner_ref"])
                if partner:
                    vals["partner_id"] = partner.id
                elif vals["status"] == "ok":
                    vals["status"] = "partner"
                    messages.append(
                        self.env._(
                            "Receivable or payable line without a known partner "
                            "(%(ref)s).",
                            ref=vals["partner_ref"] or "-",
                        )
                    )
            if vals["plant_code"]:
                branch = branches.filtered(
                    lambda b, code=vals["plant_code"]: b.code == code
                )
                if branch.analytic_account_id:
                    vals["branch_id"] = branch.id
                elif vals["status"] == "ok":
                    vals["status"] = "plant"
                    messages.append(
                        self.env._("Unknown plant %(code)s.", code=vals["plant_code"])
                    )
            if vals.get("debit", 0) < 0 or vals.get("credit", 0) < 0 or (
                vals.get("debit") and vals.get("credit")
            ):
                if vals["status"] == "ok":
                    vals["status"] = "amount"
                messages.append(
                    self.env._("Give either a positive debit or a positive credit.")
                )
            if any("Unreadable" in message for message in messages) and vals[
                "status"
            ] == "ok":
                vals["status"] = "amount"
            vals["message"] = " ".join(messages)
            vals_list.append(vals)
        return vals_list

    def _reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Import Opening Balances"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _existing_entry(self):
        """A posted opening entry of this date that was not reversed."""
        self.ensure_one()
        moves = self.env["account.move"].sudo().search(
            [
                ("company_id", "=", self.company_id.id),
                ("earlydryer_kind", "=", "opening_balance"),
                ("date", "=", self.date),
                ("state", "=", "posted"),
            ]
        )
        return moves.filtered(lambda move: not move.reversal_move_ids.filtered(
            lambda reversal: reversal.state == "posted"
        ))[:1]

    def action_preview(self):
        """Dry run: reads and checks the file, posts nothing."""
        self.ensure_one()
        self._earlydryer_check_right()
        self.line_ids.unlink()
        self.write(
            {
                "line_ids": [Command.create(vals) for vals in self._preview_vals()],
                "state": "preview",
            }
        )
        return self._reopen()

    def action_back(self):
        self.write({"state": "upload"})
        return self._reopen()

    def action_import(self):
        self.ensure_one()
        self._earlydryer_check_right()
        if self.state != "preview":
            self.action_preview()
        company = self.company_id
        existing = self._existing_entry()
        if existing:
            raise UserError(
                self.env._(
                    "Opening balances of %(date)s are already posted (%(move)s). "
                    "Reverse that entry first.",
                    date=self.date,
                    move=existing.name,
                )
            )
        if self.error_count:
            raise UserError(
                self.env._(
                    "%(count)s row(s) have errors: fix the file and run the dry run "
                    "again.",
                    count=self.error_count,
                )
            )
        if not self.line_ids:
            raise UserError(self.env._("The file has no rows."))
        journal = company.earlydryer_opening_journal_id
        if not journal:
            raise UserError(self.env._("Run the accounting setup first (Opening balances journal)."))
        difference = self.difference
        if not company.currency_id.is_zero(difference) and not self.confirm_difference:
            raise UserError(
                self.env._(
                    "Debits and credits differ by %(amount)s. Check the file, or "
                    "confirm booking the difference on Opening balance equity.",
                    amount=company.currency_id.format(difference),
                )
            )
        label = self.env._("Opening balance %(date)s", date=self.date)
        commands = []
        for line in self.line_ids:
            vals = {
                "name": line.label or label,
                "account_id": line.account_id.id,
                "partner_id": line.partner_id.id or False,
                "debit": line.debit,
                "credit": line.credit,
            }
            if line.date_maturity:
                vals["date_maturity"] = line.date_maturity
            plant = line.branch_id.analytic_account_id
            if plant:
                vals["analytic_distribution"] = {str(plant.id): 100.0}
            commands.append(Command.create(vals))
        if not company.currency_id.is_zero(difference):
            equity = company.earlydryer_opening_equity_account_id or (
                company.get_unaffected_earnings_account()
            )
            commands.append(
                Command.create(
                    {
                        "name": self.env._("Opening balance difference"),
                        "account_id": equity.id,
                        "debit": -difference if difference < 0 else 0.0,
                        "credit": difference if difference > 0 else 0.0,
                    }
                )
            )
        move = (
            self.env["account.move"]
            .sudo()
            .create(
                {
                    "move_type": "entry",
                    "journal_id": journal.id,
                    "company_id": company.id,
                    "date": self.date,
                    "ref": f"{label} ({self.filename or ''})",
                    "earlydryer_kind": "opening_balance",
                    "earlydryer_opening_hash": self._file_hash(),
                    "line_ids": commands,
                }
            )
        )
        move.action_post()
        self.write({"state": "done", "move_id": move.id})
        return self._reopen()
