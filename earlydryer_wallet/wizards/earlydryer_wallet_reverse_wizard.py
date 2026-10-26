# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerWalletReverseWizard(models.TransientModel):
    _name = "earlydryer.wallet.reverse.wizard"
    _description = "Reverse a Wallet Transaction"

    transaction_id = fields.Many2one(
        "earlydryer.wallet.transaction", required=True, readonly=True
    )
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        reversal = self.transaction_id._earlydryer_reverse(self.reason)
        return {
            "type": "ir.actions.act_window",
            "res_model": reversal._name,
            "res_id": reversal.id,
            "view_mode": "form",
        }
