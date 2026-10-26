# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    earlydryer_settlement = fields.Boolean(
        string="Balance Settlement",
        readonly=True,
        copy=False,
        help="POS payment of a customer's balance: credits the customer's "
        "receivable and is reconciled with it when the session closes.",
    )
