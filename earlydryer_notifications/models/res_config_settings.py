# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"
    earlydryer_notify_quiet_start = fields.Float(
        default=21, config_parameter="earlydryer_notify.quiet_start"
    )
    earlydryer_notify_quiet_end = fields.Float(
        default=7, config_parameter="earlydryer_notify.quiet_end"
    )
    earlydryer_notify_retention_days = fields.Integer(
        default=365, config_parameter="earlydryer_notify.retention_days"
    )

    @api.constrains(
        "earlydryer_notify_quiet_start",
        "earlydryer_notify_quiet_end",
        "earlydryer_notify_retention_days",
    )
    def _check_notify_settings(self):
        for settings in self:
            if (
                not 0 <= settings.earlydryer_notify_quiet_start < 24
                or not 0 <= settings.earlydryer_notify_quiet_end < 24
                or settings.earlydryer_notify_retention_days < 1
            ):
                raise ValidationError(
                    self.env._(
                        "Use hours between 0 and 24 and a positive retention period."
                    )
                )
