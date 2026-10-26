# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerAccountingSetupPosLine(models.TransientModel):
    """Summary of the POS payment methods after the setup."""

    _name = "earlydryer.accounting.setup.pos.line"
    _description = "Earlydryer Accounting Setup POS Summary"
    _order = "config_id, sequence, id"

    wizard_id = fields.Many2one(
        "earlydryer.accounting.setup.wizard", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)
    config_id = fields.Many2one("pos.config", string="Point of Sale", readonly=True)
    kind = fields.Char(readonly=True)
    method_id = fields.Many2one(
        "pos.payment.method", string="Payment Method", readonly=True
    )
    journal_id = fields.Many2one("account.journal", readonly=True)
    action = fields.Char(readonly=True)
