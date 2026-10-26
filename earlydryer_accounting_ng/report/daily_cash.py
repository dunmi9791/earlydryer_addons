# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from collections import defaultdict

from odoo import api, fields, models


class ReportDailyCash(models.AbstractModel):
    """Daily cash report of a plant. Every figure is read from the posted
    entries of the plant cash account and from the POS payments; nothing is
    stored by this report."""

    _name = "report.earlydryer_accounting_ng.report_daily_cash"
    _description = "Earlydryer Daily Cash Report"

    @api.model
    def _earlydryer_balance(self, account, domain):
        groups = (
            self.env["account.move.line"]
            .sudo()
            ._read_group(
                [("account_id", "=", account.id), ("parent_state", "=", "posted"), *domain],
                [],
                ["balance:sum"],
            )
        )
        return groups[0][0] or 0.0

    @api.model
    def _earlydryer_daily_cash_data(self, branch, day):
        branch.ensure_one()
        branch._earlydryer_check_cash_right("report")
        branch = branch.sudo()
        day = fields.Date.to_date(day)
        company = branch.company_id
        currency = company.currency_id
        account = branch.earlydryer_cash_account_id
        journal = branch.cash_journal_id
        data = {
            "branch": branch,
            "date": day,
            "currency": currency,
            "account": account,
            "opening": 0.0,
            "pos_cash": 0.0,
            "wallet_topups_cash": 0.0,
            "settlements_cash": 0.0,
            "rider_handovers": 0.0,
            "lodgements": 0.0,
            "differences": 0.0,
            "other": 0.0,
            "closing": 0.0,
            "float": branch.earlydryer_cash_float,
            "non_cash": [],
            "sessions": self.env["pos.session"],
            "lines": self.env["account.move.line"],
        }
        if not account:
            return data
        data["opening"] = self._earlydryer_balance(account, [("date", "<", day)])
        lines = (
            self.env["account.move.line"]
            .sudo()
            .search(
                [
                    ("account_id", "=", account.id),
                    ("parent_state", "=", "posted"),
                    ("date", "=", day),
                ],
                order="id",
            )
        )
        data["lines"] = lines
        diff_accounts = journal.profit_account_id | journal.loss_account_id
        sessions = self.env["pos.session"]
        for line in lines:
            move = line.move_id
            statement_line = move.statement_line_id
            if move.earlydryer_kind == "lodgement":
                data["lodgements"] += line.balance
            elif move.earlydryer_kind == "rider_handover":
                data["rider_handovers"] += line.balance
            elif statement_line.pos_session_id and (
                (move.line_ids - line).account_id & diff_accounts
            ):
                data["differences"] += line.balance
            elif statement_line.pos_session_id:
                data["pos_cash"] += line.balance
                sessions |= statement_line.pos_session_id
            else:
                data["other"] += line.balance
        data["closing"] = data["opening"] + sum(lines.mapped("balance"))
        # sessions of the plant's tills closed that day, cash or not
        sessions |= (
            self.env["pos.session"]
            .sudo()
            .search(
                [
                    ("config_id.earlydryer_branch_id", "=", branch.id),
                    ("state", "=", "closed"),
                    ("move_id.date", "=", day),
                ]
            )
        )
        data["sessions"] = sessions
        payments = sessions.order_ids.payment_ids
        by_method = defaultdict(lambda: {"amount": 0.0, "orders": set()})
        for payment in payments:
            method = payment.payment_method_id
            if method.is_cash_count:
                order = payment.pos_order_id
                share = payment.amount / order.amount_paid if order.amount_paid else 0.0
                for order_line in order.lines:
                    kind = order_line.product_id.earlydryer_kind
                    if kind == "wallet_topup":
                        data["wallet_topups_cash"] += order_line.price_subtotal_incl * share
                    elif kind == "settlement":
                        data["settlements_cash"] += order_line.price_subtotal_incl * share
                continue
            by_method[method]["amount"] += payment.amount
            by_method[method]["orders"].add(payment.pos_order_id.id)
        data["non_cash"] = [
            {
                "method": method,
                "kind": method.earlydryer_is_wallet and self.env._("Wallet")
                or (method.type == "pay_later" and self.env._("Customer Account"))
                or method.journal_id.name,
                "amount": values["amount"],
                "orders": len(values["orders"]),
            }
            for method, values in sorted(by_method.items(), key=lambda item: item[0].name)
        ]
        for key in (
            "opening",
            "pos_cash",
            "wallet_topups_cash",
            "settlements_cash",
            "rider_handovers",
            "lodgements",
            "differences",
            "other",
            "closing",
        ):
            data[key] = currency.round(data[key])
        return data

    @api.model
    def _get_report_values(self, docids, data=None):
        branches = self.env["earlydryer.branch"].browse(docids)
        day = (data or {}).get("date") or fields.Date.context_today(self)
        return {
            "doc_ids": docids,
            "doc_model": "earlydryer.branch",
            "docs": branches.sudo(),
            "reports": [
                self._earlydryer_daily_cash_data(branch, day) for branch in branches
            ],
        }
