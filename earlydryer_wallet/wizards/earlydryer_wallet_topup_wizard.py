# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError


class EarlydryerWalletTopupWizard(models.TransientModel):
    _name = "earlydryer.wallet.topup.wizard"
    _description = "Top up a Customer Wallet"

    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount = fields.Monetary(required=True)
    min_amount = fields.Monetary(related="company_id.earlydryer_wallet_min_topup")
    journal_id = fields.Many2one(
        "account.journal",
        string="Paid Into",
        required=True,
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal(),
        help="Cash journal of the plant for cash, a bank journal for transfers "
        "and card payments.",
    )
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Branch",
        default=lambda self: self.env.user.earlydryer_branch_id,
    )
    reference = fields.Char(help="Bank transfer reference or receipt number.")
    balance = fields.Monetary(
        related="partner_id.earlydryer_wallet_balance", string="Current Balance"
    )

    @api.model
    def _default_journal(self):
        return self.env.user.earlydryer_branch_id.sudo().cash_journal_id

    @api.onchange("earlydryer_branch_id")
    def _onchange_earlydryer_branch_id(self):
        cash = self.earlydryer_branch_id.sudo().cash_journal_id
        if cash and (not self.journal_id or self.journal_id.type == "cash"):
            self.journal_id = cash

    def action_confirm(self):
        self.ensure_one()
        Tx = self.env["earlydryer.wallet.transaction"]
        Tx._earlydryer_check_topup_journal(self.journal_id)
        if self.currency_id.compare_amounts(self.amount, self.min_amount) < 0 or (
            self.currency_id.compare_amounts(self.amount, 0.0) <= 0
        ):
            raise UserError(
                self.env._(
                    "The minimum top-up is %(amount)s.",
                    amount=Tx._earlydryer_format(max(self.min_amount, 0.0)),
                )
            )
        tx = Tx._earlydryer_new(
            self.partner_id,
            "topup",
            self.amount,
            company=self.company_id,
            payment_journal_id=self.journal_id.id,
            earlydryer_branch_id=self.earlydryer_branch_id.id,
            reference=self.reference,
        )
        tx.action_post()
        return tx.wallet_id.action_view_transactions()
