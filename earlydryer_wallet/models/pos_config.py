# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class PosConfig(models.Model):
    _inherit = "pos.config"

    earlydryer_wallet_enabled = fields.Boolean(
        string="Wallet Payments",
        compute="_compute_earlydryer_wallet_enabled",
        help="The till has the Wallet payment method.",
    )

    @api.depends("payment_method_ids.earlydryer_is_wallet")
    def _compute_earlydryer_wallet_enabled(self):
        for config in self:
            config.earlydryer_wallet_enabled = any(
                config.payment_method_ids.mapped("earlydryer_is_wallet")
            )

    def _earlydryer_account_methods(self):
        # the wallet is journal-less too, but it is not the customer account
        return (
            super()
            ._earlydryer_account_methods()
            .filtered(lambda method: not method.earlydryer_is_wallet)
        )

    def action_earlydryer_add_wallet_payment(self):
        """Button: add the company's Wallet payment method to the till."""
        for config in self:
            if not config.earlydryer_enabled:
                raise UserError(
                    self.env._(
                        "%(pos)s is not an Earlydryer laundry counter.",
                        pos=config.display_name,
                    )
                )
            company = config.company_id
            company._earlydryer_wallet_setup()
            company._earlydryer_wallet_check_setup()
            method = company._earlydryer_wallet_pos_method()
            if method not in config.payment_method_ids:
                config.payment_method_ids = [Command.link(method.id)]
        return True

    def _earlydryer_wallet_payload(self):
        """Wallet data loaded with the till: non-zero balances only."""
        self.ensure_one()
        product = self.env.ref(
            "earlydryer_wallet.product_wallet_topup", raise_if_not_found=False
        )
        return {
            "balances": self.env["earlydryer.wallet"]._earlydryer_pos_balances(
                self.company_id
            ),
            "method_ids": self.payment_method_ids.filtered("earlydryer_is_wallet").ids,
            "topup_product_id": product.id if product else False,
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
        }

    @api.model
    def _load_pos_data_read(self, records, config):
        read_records = super()._load_pos_data_read(records, config)
        if read_records and config.earlydryer_enabled:
            read_records[0]["_earlydryer_wallet"] = config._earlydryer_wallet_payload()
        return read_records
