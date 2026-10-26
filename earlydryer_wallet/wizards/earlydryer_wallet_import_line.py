# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

STATUSES = [
    ("match", "Matched"),
    ("create", "New Customer"),
    ("skip", "Skipped"),
    ("error", "Error"),
]


class EarlydryerWalletImportLine(models.TransientModel):
    _name = "earlydryer.wallet.import.line"
    _description = "Wallet Balance Import Row"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "earlydryer.wallet.import.wizard", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(string="Row")
    ref = fields.Char()
    name = fields.Char()
    phone = fields.Char()
    phone_normalized = fields.Char(string="Normalised Phone")
    balance = fields.Float()
    branch_code = fields.Char()
    branch_id = fields.Many2one("earlydryer.branch")
    note = fields.Char()
    partner_id = fields.Many2one("res.partner", string="Customer")
    status = fields.Selection(STATUSES, required=True, default="error")
    message = fields.Char()
