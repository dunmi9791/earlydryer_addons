# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models
from odoo.exceptions import UserError

from ..models.earlydryer_wallet import FINANCE


class EarlydryerWalletRefundWizard(models.TransientModel):
    _name = "earlydryer.wallet.refund.wizard"
    _description = "Refund a Customer Wallet"

    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    balance = fields.Monetary(
        related="partner_id.earlydryer_wallet_balance", string="Current Balance"
    )
    amount = fields.Monetary(required=True)
    journal_id = fields.Many2one(
        "account.journal",
        string="Paid From",
        required=True,
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]",
    )
    reason = fields.Text(required=True)
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Branch",
        default=lambda self: self.env.user.earlydryer_branch_id,
    )

    def action_confirm(self):
        """Draft refund, posted at once or after approval (always needed by
        the shipped rules)."""
        self.ensure_one()
        Wallet = self.env["earlydryer.wallet"]
        Wallet._earlydryer_check_right("refund")
        wallet = Wallet._earlydryer_get(self.partner_id, self.company_id)
        currency = self.currency_id
        if (
            not wallet
            or currency.compare_amounts(self.amount, wallet.sudo().balance) > 0
        ):
            raise UserError(
                self.env._("The refund cannot be more than the wallet balance.")
            )
        if wallet.sudo().state == "blocked" and not self.env.user.has_group(FINANCE):
            raise UserError(self.env._("Only Finance refunds a blocked wallet."))
        tx = self.env["earlydryer.wallet.transaction"]._earlydryer_new(
            self.partner_id,
            "refund",
            self.amount,
            company=self.company_id,
            payment_journal_id=self.journal_id.id,
            reason=self.reason,
            earlydryer_branch_id=self.earlydryer_branch_id.id,
        )
        tx._earlydryer_submit()
        return {
            "type": "ir.actions.act_window",
            "res_model": tx._name,
            "res_id": tx.id,
            "view_mode": "form",
        }
