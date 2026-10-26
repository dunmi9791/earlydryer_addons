# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    earlydryer_is_wallet = fields.Boolean(
        string="Earlydryer Wallet",
        help="Pays from the customer's prepaid wallet. No journal (Odoo 19 type "
        "Customer Account) and Identify Customer: at session closing each "
        "wallet payment debits the Customer Advances account with the customer, "
        "instead of the receivable.",
    )

    @api.constrains("earlydryer_is_wallet", "journal_id", "split_transactions")
    def _check_earlydryer_wallet(self):
        for method in self.filtered("earlydryer_is_wallet"):
            if method.journal_id or not method.split_transactions:
                raise ValidationError(
                    self.env._(
                        "%(method)s: a wallet payment method has no journal and "
                        "identifies the customer.",
                        method=method.display_name,
                    )
                )

    @api.model
    def _load_pos_data_fields(self, config):
        return [*super()._load_pos_data_fields(config), "earlydryer_is_wallet"]
