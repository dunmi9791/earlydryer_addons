# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"
    earlydryer_min_minutes_per_item = fields.Float(
        default=0.5, config_parameter="earlydryer_reporting.min_minutes_per_item"
    )
