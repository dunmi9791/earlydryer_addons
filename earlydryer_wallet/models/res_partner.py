# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    earlydryer_wallet_id = fields.Many2one(
        "earlydryer.wallet",
        string="Wallet",
        compute="_compute_earlydryer_wallet",
        compute_sudo=True,
    )
    earlydryer_wallet_balance = fields.Monetary(
        string="Wallet Balance",
        compute="_compute_earlydryer_wallet",
        compute_sudo=True,
        currency_field="earlydryer_wallet_currency_id",
    )
    earlydryer_wallet_currency_id = fields.Many2one(
        "res.currency", compute="_compute_earlydryer_wallet", compute_sudo=True
    )

    def _compute_earlydryer_wallet(self):
        company = self.env.company
        commercial = self.commercial_partner_id
        wallets = self.env["earlydryer.wallet"].search(
            [("partner_id", "in", commercial.ids), ("company_id", "=", company.id)]
        )
        by_partner = {wallet.partner_id: wallet for wallet in wallets}
        for partner in self:
            wallet = by_partner.get(
                partner.commercial_partner_id, self.env["earlydryer.wallet"]
            )
            partner.earlydryer_wallet_id = wallet
            partner.earlydryer_wallet_balance = wallet.balance
            partner.earlydryer_wallet_currency_id = company.currency_id

    def _earlydryer_wallet_wizard(self, xmlid):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)
        action["context"] = {
            "default_partner_id": self.commercial_partner_id.id,
            "dialog_size": "medium",
        }
        return action

    def action_earlydryer_wallet_open(self):
        self.ensure_one()
        wallet = self.earlydryer_wallet_id
        if not wallet:
            return self.action_earlydryer_wallet_topup()
        return {
            "type": "ir.actions.act_window",
            "res_model": "earlydryer.wallet",
            "res_id": wallet.id,
            "view_mode": "form",
        }

    def action_earlydryer_wallet_topup(self):
        return self._earlydryer_wallet_wizard(
            "earlydryer_wallet.earlydryer_wallet_topup_wizard_action"
        )

    def action_earlydryer_wallet_refund(self):
        return self._earlydryer_wallet_wizard(
            "earlydryer_wallet.earlydryer_wallet_refund_wizard_action"
        )

    def action_earlydryer_wallet_credit(self):
        return self._earlydryer_wallet_wizard(
            "earlydryer_wallet.earlydryer_wallet_credit_wizard_action"
        )

    def action_earlydryer_wallet_statement(self):
        return self._earlydryer_wallet_wizard(
            "earlydryer_wallet.earlydryer_wallet_statement_wizard_action"
        )
