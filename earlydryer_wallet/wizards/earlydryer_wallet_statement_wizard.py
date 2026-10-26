# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerWalletStatementWizard(models.TransientModel):
    _name = "earlydryer.wallet.statement.wizard"
    _description = "Wallet Statement"

    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.start_of(fields.Date.today(), "month"),
    )
    date_to = fields.Date(required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        wallet = self.env["earlydryer.wallet"]._earlydryer_get(self.partner_id)
        return self.env.ref(
            "earlydryer_wallet.action_report_wallet_statement"
        ).report_action(
            wallet,
            data={
                "wallet_ids": wallet.ids,
                "partner_id": self.partner_id.commercial_partner_id.id,
                "date_from": fields.Date.to_string(self.date_from),
                "date_to": fields.Date.to_string(self.date_to),
            },
        )
