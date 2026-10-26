# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    earlydryer_wallet_account_id = fields.Many2one(
        related="company_id.earlydryer_wallet_account_id", readonly=False
    )
    earlydryer_wallet_journal_id = fields.Many2one(
        related="company_id.earlydryer_wallet_journal_id", readonly=False
    )
    earlydryer_wallet_credit_account_id = fields.Many2one(
        related="company_id.earlydryer_wallet_credit_account_id", readonly=False
    )
    earlydryer_wallet_opening_account_id = fields.Many2one(
        related="company_id.earlydryer_wallet_opening_account_id", readonly=False
    )
    earlydryer_wallet_auto_apply = fields.Boolean(
        related="company_id.earlydryer_wallet_auto_apply", readonly=False
    )
    earlydryer_wallet_min_topup = fields.Monetary(
        related="company_id.earlydryer_wallet_min_topup", readonly=False
    )
