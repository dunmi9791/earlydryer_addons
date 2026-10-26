# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError


class EarlydryerWalletSpendWizard(models.TransientModel):
    _name = "earlydryer.wallet.spend.wizard"
    _description = "Pay from a Customer Wallet"

    invoice_id = fields.Many2one("account.move", readonly=True)
    laundry_job_id = fields.Many2one("laundry.job", readonly=True)
    partner_id = fields.Many2one(
        "res.partner", compute="_compute_amounts", string="Customer"
    )
    company_id = fields.Many2one("res.company", compute="_compute_amounts")
    currency_id = fields.Many2one(related="company_id.currency_id")
    balance = fields.Monetary(compute="_compute_amounts", string="Wallet Balance")
    due = fields.Monetary(compute="_compute_amounts", string="Amount Due")
    amount = fields.Monetary(compute="_compute_amount", store=True, readonly=False)

    @api.depends("invoice_id", "laundry_job_id")
    def _compute_amounts(self):
        for wizard in self:
            document = wizard.invoice_id or wizard.laundry_job_id
            wizard.partner_id = document.partner_id
            wizard.company_id = document.company_id or self.env.company
            wizard.balance = document.earlydryer_wallet_balance
            wizard.due = (
                wizard.invoice_id.amount_residual
                if wizard.invoice_id
                else wizard.laundry_job_id.amount_due
            )

    @api.depends("invoice_id", "laundry_job_id")
    def _compute_amount(self):
        for wizard in self:
            wizard._compute_amounts()
            wizard.amount = max(min(wizard.balance, wizard.due), 0.0)

    def action_confirm(self):
        self.ensure_one()
        currency = self.currency_id
        if currency.compare_amounts(self.amount, 0.0) <= 0:
            raise UserError(self.env._("The amount must be positive."))
        if currency.compare_amounts(self.amount, self.balance) > 0:
            raise UserError(
                self.env._("The wallet holds only %(balance)s.", balance=self.balance)
            )
        if self.invoice_id:
            self.env["earlydryer.wallet"]._earlydryer_check_right("spend")
            self.invoice_id._earlydryer_wallet_spend(self.amount)
        else:
            self.laundry_job_id._earlydryer_wallet_spend(self.amount)
        return {"type": "ir.actions.act_window_close"}
