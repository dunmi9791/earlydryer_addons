# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time

from odoo import api, fields, models


class ReportWalletStatement(models.AbstractModel):
    _name = "report.earlydryer_wallet.report_wallet_statement"
    _description = "Wallet Statement Report"

    @api.model
    def _earlydryer_statement(self, wallet, date_from, date_to):
        """Opening balance, posted transactions of the period, closing balance."""
        Tx = self.env["earlydryer.wallet.transaction"].sudo()
        start = datetime.combine(date_from, time.min)
        end = datetime.combine(date_to, time.max)
        base = [("wallet_id", "=", wallet.id), ("state", "=", "posted")]
        opening = sum(Tx.search([*base, ("date", "<", start)]).mapped("signed_amount"))
        transactions = Tx.search(
            [*base, ("date", ">=", start), ("date", "<=", end)], order="date, id"
        )
        rows = []
        running = opening
        for tx in transactions:
            running += tx.signed_amount
            rows.append({"tx": tx, "balance": running})
        return {
            "wallet": wallet,
            "opening": opening,
            "rows": rows,
            "closing": running,
            "date_from": date_from,
            "date_to": date_to,
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        today = fields.Date.context_today(self)
        date_from = fields.Date.to_date(data.get("date_from")) or today.replace(day=1)
        date_to = fields.Date.to_date(data.get("date_to")) or today
        wallets = self.env["earlydryer.wallet"].browse(data.get("wallet_ids") or docids)
        wallets.check_access("read")
        return {
            "doc_ids": wallets.ids,
            "doc_model": "earlydryer.wallet",
            "docs": wallets,
            "statements": [
                self._earlydryer_statement(wallet, date_from, date_to)
                for wallet in wallets
            ],
        }
