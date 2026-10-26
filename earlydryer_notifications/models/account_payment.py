# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def action_post(self):
        result = super().action_post()
        for payment in self.filtered(
            lambda p: p.payment_type == "inbound" and p.partner_type == "customer"
        ):
            self.env["earlydryer.notify.message"].notify(
                "payment_received", payment, context={"occurrence": str(payment.id)}
            )
        return result
