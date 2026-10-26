# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

# days overdue: (label, lowest, highest)
AGEING_BUCKETS = (
    ("Not due", None, 0),
    ("1-30", 1, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
)


class ReportCustomerStatement(models.AbstractModel):
    """Statement of account of a customer: open and recent invoices,
    payments, wallet balance and ageing. Reused by the corporate module."""

    _name = "report.earlydryer_accounting_ng.report_customer_statement"
    _description = "Earlydryer Customer Statement"

    @api.model
    def _earlydryer_statement_data(self, partner, date_to=None):
        partner = partner.commercial_partner_id
        date_to = fields.Date.to_date(date_to) or fields.Date.context_today(self)
        company = self.env.company
        MoveLine = self.env["account.move.line"]
        lines = MoveLine.search(
            [
                ("partner_id", "=", partner.id),
                ("account_id.account_type", "=", "asset_receivable"),
                ("parent_state", "=", "posted"),
                ("company_id", "=", company.id),
                ("date", "<=", date_to),
            ],
            order="date, id",
        )
        balance = 0.0
        rows = []
        for line in lines:
            balance += line.balance
            rows.append(
                {
                    "date": line.date,
                    "ref": line.move_id.name,
                    "label": line.move_id.ref or line.name or "",
                    "due": line.date_maturity,
                    "debit": line.debit,
                    "credit": line.credit,
                    "balance": balance,
                }
            )
        open_lines = lines.filtered(lambda line: not line.reconciled)
        ageing = []
        for label, low, high in AGEING_BUCKETS:
            amount = 0.0
            for line in open_lines:
                overdue = (date_to - (line.date_maturity or line.date)).days
                if (low is None or overdue >= low) and (high is None or overdue <= high):
                    amount += line.amount_residual
            ageing.append({"label": label, "amount": amount})
        wallet = self.env["earlydryer.wallet"].sudo()._earlydryer_get(partner, company)
        return {
            "partner": partner,
            "date_to": date_to,
            "currency": company.currency_id,
            "rows": rows,
            "balance": balance,
            "due": sum(open_lines.mapped("amount_residual")),
            "ageing": ageing,
            "wallet_balance": wallet.balance if wallet else 0.0,
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        partners = self.env["res.partner"].browse(docids)
        date_to = (data or {}).get("date_to")
        return {
            "doc_ids": docids,
            "doc_model": "res.partner",
            "docs": partners,
            "statements": {
                partner.id: self._earlydryer_statement_data(partner, date_to)
                for partner in partners
            },
        }
