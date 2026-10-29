# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerLogisticsFailReason(models.Model):
    _name = "earlydryer.logistics.fail.reason"
    _description = "Earlydryer Failed Stop Reason"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    stop_type = fields.Selection(
        [("pickup", "Pickups"), ("delivery", "Deliveries"), ("both", "Both")],
        required=True,
        default="both",
    )
    fee_applies = fields.Boolean(
        help="A failed-delivery fee is charged on the next attempt, when the "
        "plant's failed-fee rule is not None (PLACEHOLDER: off by default).",
    )
    note_required = fields.Boolean()

    _code_uniq = models.Constraint("unique(code)", "The reason code must be unique.")
