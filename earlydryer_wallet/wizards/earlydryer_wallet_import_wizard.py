# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import csv
import io
from datetime import datetime, time

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from ..tools import normalize_ng_phone

COLUMNS = ("ref", "name", "phone", "balance")
OPTIONAL_COLUMNS = ("branch_code", "note")


class EarlydryerWalletImportWizard(models.TransientModel):
    _name = "earlydryer.wallet.import.wizard"
    _description = "Import Wallet Balances"

    file = fields.Binary(required=True, attachment=False)
    filename = fields.Char()
    as_of_date = fields.Date(
        string="Balances as of", required=True, default=fields.Date.context_today
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    state = fields.Selection(
        [("upload", "Upload"), ("preview", "Preview"), ("done", "Done")],
        default="upload",
        required=True,
    )
    line_ids = fields.One2many(
        "earlydryer.wallet.import.line", "wizard_id", string="Rows"
    )
    count_match = fields.Integer(compute="_compute_totals", string="Matched")
    count_create = fields.Integer(compute="_compute_totals", string="New Customers")
    count_skip = fields.Integer(compute="_compute_totals", string="Skipped")
    count_error = fields.Integer(compute="_compute_totals", string="Errors")
    total = fields.Monetary(compute="_compute_totals", string="Total to Import")
    move_id = fields.Many2one("account.move", string="Summary Entry", readonly=True)

    @api.depends("line_ids.status", "line_ids.balance")
    def _compute_totals(self):
        for wizard in self:
            lines = wizard.line_ids
            wizard.count_match = len(
                lines.filtered(lambda line: line.status == "match")
            )
            wizard.count_create = len(
                lines.filtered(lambda line: line.status == "create")
            )
            wizard.count_skip = len(lines.filtered(lambda line: line.status == "skip"))
            wizard.count_error = len(
                lines.filtered(lambda line: line.status == "error")
            )
            wizard.total = sum(
                lines.filtered(lambda line: line.status in ("match", "create")).mapped(
                    "balance"
                )
            )

    # ------------------------------------------------------------------
    # Reading the file
    # ------------------------------------------------------------------

    def _read_rows(self):
        """Rows of the CSV or XLSX file as dicts with lowercase keys."""
        self.ensure_one()
        content = base64.b64decode(self.file or b"")
        name = (self.filename or "").lower()
        if name.endswith(".xlsx") or content[:2] == b"PK":
            import openpyxl  # external dependency of the manifest

            book = openpyxl.load_workbook(
                io.BytesIO(content), read_only=True, data_only=True
            )
            sheet = book.worksheets[0]
            values = list(sheet.iter_rows(values_only=True))
            if not values:
                return []
            header = [str(cell or "").strip().lower() for cell in values[0]]
            rows = [
                dict(zip(header, row, strict=False))
                for row in values[1:]
                if any(cell not in (None, "") for cell in row)
            ]
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
            reader = csv.DictReader(io.StringIO(text))
            reader.fieldnames = [
                (field or "").strip().lower() for field in reader.fieldnames or []
            ]
            rows = [
                row
                for row in reader
                if any(
                    (value or "").strip()
                    for value in row.values()
                    if isinstance(value, str)
                )
            ]
        if rows:
            missing = [column for column in COLUMNS if column not in rows[0]]
            if missing:
                raise UserError(
                    self.env._(
                        "Missing column(s): %(columns)s. Expected ref, name, phone, "
                        "balance and optionally branch_code and note.",
                        columns=", ".join(missing),
                    )
                )
        return rows

    @api.model
    def _parse_amount(self, value):
        if isinstance(value, int | float):
            return float(value)
        text = str(value or "").replace(",", "").replace("₦", "").strip()
        if text.startswith("(") and text.endswith(")"):
            text = f"-{text[1:-1]}"
        return float(text)

    def _match_partner(self, name, phone):
        """Existing customer by normalised phone, then by exact name."""
        Partner = self.env["res.partner"].sudo()
        if phone:
            digits = phone.lstrip("+")[-9:]
            for partner in Partner.search([("phone", "ilike", digits)], order="id"):
                if normalize_ng_phone(partner.phone) == phone:
                    return partner.commercial_partner_id
        if name:
            partner = Partner.search([("name", "=", name)], order="id", limit=1)
            if partner:
                return partner.commercial_partner_id
        return Partner.browse()

    def _preview_vals(self):
        """Row values with their status (nothing is written)."""
        self.ensure_one()
        Tx = self.env["earlydryer.wallet.transaction"].sudo()
        Branch = self.env["earlydryer.branch"].sudo()
        currency = self.currency_id
        seen = set()
        vals_list = []
        for index, row in enumerate(self._read_rows(), start=2):
            ref = str(row.get("ref") or "").strip()
            name = str(row.get("name") or "").strip()
            phone_raw = str(row.get("phone") or "").strip()
            phone = normalize_ng_phone(phone_raw)
            branch_code = str(row.get("branch_code") or "").strip()
            vals = {
                "sequence": index,
                "ref": ref,
                "name": name,
                "phone": phone_raw,
                "phone_normalized": phone,
                "branch_code": branch_code,
                "note": str(row.get("note") or "").strip(),
                "status": "error",
            }
            vals_list.append(vals)
            try:
                balance = self._parse_amount(row.get("balance"))
            except ValueError:
                vals["message"] = self.env._(
                    "Balance %(value)s is not a number.", value=row.get("balance")
                )
                continue
            vals["balance"] = balance
            if not ref:
                vals["message"] = self.env._("The ref column is empty.")
                continue
            if ref in seen:
                vals["message"] = self.env._(
                    "Ref %(ref)s appears twice in the file.", ref=ref
                )
                continue
            seen.add(ref)
            if currency.compare_amounts(balance, 0.0) < 0:
                vals["message"] = self.env._(
                    "Negative balance: the customer owes Earlydryer. Put it in the "
                    "opening receivables (accounting), not in the wallet."
                )
                continue
            if not name and not phone:
                vals["message"] = self.env._("Give a name or a phone.")
                continue
            if branch_code:
                branch = Branch.search([("code", "=ilike", branch_code)], limit=1)
                if not branch:
                    vals["message"] = self.env._(
                        "Unknown branch code %(code)s.", code=branch_code
                    )
                    continue
                vals["branch_id"] = branch.id
            if Tx.search_count(
                [("company_id", "=", self.company_id.id), ("import_ref", "=", ref)],
                limit=1,
            ):
                vals.update(status="skip", message=self.env._("Already imported."))
                continue
            if currency.is_zero(balance):
                vals.update(status="skip", message=self.env._("Zero balance."))
                continue
            partner = self._match_partner(name, phone)
            if partner:
                vals.update(status="match", partner_id=partner.id)
            else:
                vals.update(
                    status="create", message=self.env._("A new customer is created.")
                )
        return vals_list

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_preview(self):
        """Dry run: read and match, post nothing."""
        self.ensure_one()
        self.env["earlydryer.wallet"]._earlydryer_check_right("import")
        self.line_ids = [Command.clear()] + [
            Command.create(vals) for vals in self._preview_vals()
        ]
        self.state = "preview"
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.write({"state": "upload", "line_ids": [Command.clear()]})
        return self._reopen()

    def action_import(self):
        """Post the previewed rows (read again, so a re-import adds nothing):
        one migration transaction per row and one summary entry."""
        self.ensure_one()
        self.env["earlydryer.wallet"]._earlydryer_check_right("import")
        company = self.company_id
        company._earlydryer_wallet_check_setup()
        self.action_preview()
        rows = self.line_ids.filtered(lambda line: line.status in ("match", "create"))
        if not rows:
            raise UserError(self.env._("Nothing to import."))
        Tx = self.env["earlydryer.wallet.transaction"]
        Partner = self.env["res.partner"].sudo()
        date = datetime.combine(self.as_of_date, time(12, 0))
        transactions = Tx.browse()
        for row in rows:
            partner = row.partner_id
            if not partner:
                partner = Partner.create(
                    {
                        "name": row.name or row.phone_normalized,
                        "phone": row.phone_normalized or False,
                    }
                )
                row.partner_id = partner
            transactions |= Tx._earlydryer_new(
                partner,
                "migration",
                row.balance,
                company=company,
                source="import",
                import_ref=row.ref,
                date=date,
                earlydryer_branch_id=row.branch_id.id,
                reference=row.note or False,
            )
        move = self._create_summary_move(transactions)
        for tx in transactions:
            tx._earlydryer_write({"move_id": move.id})
            tx._earlydryer_post()
        self.write({"state": "done", "move_id": move.id})
        return self._reopen()

    def _create_summary_move(self, transactions):
        """Dr opening balance account (total) / Cr customer advances, one line
        per customer so the partner balances are right in the GL."""
        self.ensure_one()
        company = self.company_id
        opening = transactions[:1]._earlydryer_opening_account()
        total = sum(transactions.mapped("amount"))
        label = self.env._(
            "Wallet balances migrated as of %(date)s", date=self.as_of_date
        )
        lines = [
            Command.create(
                {
                    "name": label,
                    "account_id": opening.id,
                    "debit": total,
                }
            )
        ]
        for tx in transactions:
            lines.append(
                Command.create(
                    {
                        "name": f"{tx.name} {tx.import_ref}",
                        "account_id": company.earlydryer_wallet_account_id.id,
                        "partner_id": tx.partner_id.id,
                        "credit": tx.amount,
                    }
                )
            )
        move = (
            self.env["account.move"]
            .sudo()
            .create(
                {
                    "move_type": "entry",
                    "journal_id": company.earlydryer_wallet_journal_id.id,
                    "company_id": company.id,
                    "date": self.as_of_date,
                    "ref": f"{label} ({self.filename or ''})",
                    "line_ids": lines,
                }
            )
        )
        move.action_post()
        return move
