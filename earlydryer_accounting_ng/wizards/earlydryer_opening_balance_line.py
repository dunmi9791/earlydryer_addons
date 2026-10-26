# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerOpeningBalanceLine(models.TransientModel):
    _name = "earlydryer.opening.balance.line"
    _description = "Opening Balance Row"
    _order = "row"

    wizard_id = fields.Many2one(
        "earlydryer.opening.balance.wizard", required=True, ondelete="cascade"
    )
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    row = fields.Integer()
    account_code = fields.Char()
    account_name = fields.Char(string="Name in File")
    account_id = fields.Many2one("account.account")
    partner_ref = fields.Char()
    partner_id = fields.Many2one("res.partner")
    plant_code = fields.Char()
    branch_id = fields.Many2one("earlydryer.branch", string="Plant")
    label = fields.Char()
    debit = fields.Monetary()
    credit = fields.Monetary()
    date_maturity = fields.Date(string="Due Date")
    status = fields.Selection(
        [
            ("ok", "OK"),
            ("account", "Unknown Account"),
            ("partner", "Missing Partner"),
            ("plant", "Unknown Plant"),
            ("amount", "Wrong Amount"),
            ("advances", "Customer Advances (refused)"),
        ],
        required=True,
        default="ok",
    )
    message = fields.Char()
