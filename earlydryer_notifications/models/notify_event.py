# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class NotifyEvent(models.Model):
    _name = "earlydryer.notify.event"
    _description = "Notification Event"
    _order = "audience, code"
    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    audience = fields.Selection(
        [("customer", "Customer"), ("staff", "Staff")],
        default="customer",
        required=True,
    )
    urgent = fields.Boolean()
    channels = fields.Selection(
        [
            ("whatsapp,sms", "WhatsApp then SMS"),
            ("sms", "SMS only"),
            ("whatsapp", "WhatsApp only"),
        ],
        default="whatsapp,sms",
        required=True,
    )
    dedupe_minutes = fields.Integer(default=1440)
    allow_repeat = fields.Boolean(
        help="Allow a subsequent real occurrence. Repeated delivery of the same occurrence is still deduplicated."
    )
    branch_ids = fields.Many2many("earlydryer.branch")
    _code_unique = models.Constraint("unique(code)", "Event codes must be unique.")

    @api.constrains("dedupe_minutes")
    def _check_minutes(self):
        if any(e.dedupe_minutes < 0 for e in self):
            raise ValidationError(self.env._("Dedupe minutes cannot be negative."))
