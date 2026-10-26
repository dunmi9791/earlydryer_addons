# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time

from odoo import api, fields, models
from odoo.fields import Domain


class EarlydryerWalletControl(models.TransientModel):
    """Subledger against general ledger: the sum of the wallet balances must
    equal the balance of the Customer Advances account."""

    _name = "earlydryer.wallet.control"
    _description = "Wallet Control Report"

    date = fields.Date(required=True, default=fields.Date.context_today)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    account_id = fields.Many2one(
        related="company_id.earlydryer_wallet_account_id", string="Advances Account"
    )
    wallet_total = fields.Monetary(
        compute="_compute_control", string="Sum of Wallet Balances"
    )
    gl_balance = fields.Monetary(
        compute="_compute_control",
        string="General Ledger Balance",
        help="Credit balance of the Customer Advances account.",
    )
    difference = fields.Monetary(compute="_compute_control")
    pending_amount = fields.Monetary(
        compute="_compute_control",
        string="Till Transactions not Accounted Yet",
        help="Wallet effect of till transactions whose session is not closed "
        "(or closed after the date): the usual timing difference.",
    )
    unexplained = fields.Monetary(
        compute="_compute_control", string="Unexplained Difference"
    )
    pending_transaction_ids = fields.Many2many(
        "earlydryer.wallet.transaction",
        compute="_compute_control",
        string="Pending Till Transactions",
    )
    overdrawn_wallet_ids = fields.Many2many(
        "earlydryer.wallet", compute="_compute_control", string="Overdrawn Wallets"
    )

    @api.depends("date", "company_id")
    def _compute_control(self):
        Tx = self.env["earlydryer.wallet.transaction"].sudo()
        MoveLine = self.env["account.move.line"].sudo()
        for report in self:
            company = report.company_id
            end = datetime.combine(report.date, time.max)
            posted = Domain(
                [
                    ("company_id", "=", company.id),
                    ("state", "=", "posted"),
                    ("date", "<=", end),
                ]
            )
            wallet_total = sum(Tx.search(posted).mapped("signed_amount"))
            gl_balance = 0.0
            if company.earlydryer_wallet_account_id:
                groups = MoveLine._read_group(
                    [
                        ("account_id", "=", company.earlydryer_wallet_account_id.id),
                        ("parent_state", "=", "posted"),
                        ("date", "<=", report.date),
                        ("company_id", "=", company.id),
                    ],
                    [],
                    ["balance:sum"],
                )
                gl_balance = -(groups[0][0] or 0.0)
            pending = Tx.search(
                posted
                & Domain("source", "=", "pos")
                & Domain("move_id", "=", False)
                & (
                    Domain("pos_order_id.session_id.state", "!=", "closed")
                    | Domain("pos_order_id.session_id.move_id.date", ">", report.date)
                )
                # orders invoiced while the session was open are accounted by
                # the invoice and its payment entries, not the closing entry
                & Domain("pos_order_id.account_move", "=", False)
            )
            pending_amount = sum(pending.mapped("signed_amount"))
            report.wallet_total = wallet_total
            report.gl_balance = gl_balance
            report.difference = company.currency_id.round(wallet_total - gl_balance)
            report.pending_amount = pending_amount
            report.unexplained = company.currency_id.round(
                wallet_total - gl_balance - pending_amount
            )
            report.pending_transaction_ids = pending
            report.overdrawn_wallet_ids = (
                self.env["earlydryer.wallet"]
                .sudo()
                .search([("company_id", "=", company.id), ("overdrawn", "=", True)])
            )

    @api.model
    def action_open(self):
        """Menu entry: Finance and above only."""
        self.env["earlydryer.wallet"]._earlydryer_check_right("control")
        report = self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Wallet Control"),
            "res_model": self._name,
            "res_id": report.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model_create_multi
    def create(self, vals_list):
        self.env["earlydryer.wallet"]._earlydryer_check_right("control")
        return super().create(vals_list)
