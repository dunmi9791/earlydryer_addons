# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class WalletTransaction(models.Model):
    _inherit = "earlydryer.wallet.transaction"

    def _earlydryer_on_wallet_transaction_posted(self):
        result = super()._earlydryer_on_wallet_transaction_posted()
        for transaction in self:
            if transaction.type in ("topup", "spend"):
                self.env["earlydryer.notify.message"].notify(
                    "wallet_" + transaction.type,
                    transaction,
                    context={"occurrence": str(transaction.id)},
                )
            if transaction.overdrawn:
                self.env["earlydryer.notify.message"].notify(
                    "alert_wallet_overdraw",
                    transaction,
                    context={
                        "occurrence": str(transaction.id),
                        "value": transaction.shortfall,
                    },
                )
        return result
