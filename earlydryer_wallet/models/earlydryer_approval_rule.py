# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerApprovalRule(models.Model):
    _inherit = "earlydryer.approval.rule"

    approval_type = fields.Selection(
        selection_add=[
            ("wallet_refund", "Wallet Refund"),
            ("wallet_credit", "Wallet Credit"),
        ],
        ondelete={"wallet_refund": "cascade", "wallet_credit": "cascade"},
    )
