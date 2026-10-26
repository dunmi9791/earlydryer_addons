# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    earlydryer_uncollected_days = fields.Integer(
        string="Uncollected After (days)",
        config_parameter="earlydryer.uncollected_days",
        default=14,
        help="Days after an order is ready before it becomes Uncollected and "
        "Earlydryer's liability ends.",
    )
    earlydryer_uncollected_reminder_days = fields.Char(
        string="Reminder Days",
        config_parameter="earlydryer.uncollected_reminder_days",
        default="3,7,12",
        help="Comma-separated days after the order is ready on which the "
        "customer is reminded to collect it.",
    )

    @api.constrains(
        "earlydryer_uncollected_days", "earlydryer_uncollected_reminder_days"
    )
    def _check_earlydryer_uncollected(self):
        Job = self.env["laundry.job"]
        for settings in self:
            if settings.earlydryer_uncollected_days < 1:
                raise ValidationError(
                    self.env._("The uncollected limit must be at least one day.")
                )
            # raises on malformed values
            Job._earlydryer_parse_reminder_days(
                settings.earlydryer_uncollected_reminder_days, strict=True
            )
