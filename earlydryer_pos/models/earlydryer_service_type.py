# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models


class EarlydryerServiceType(models.Model):
    _name = "earlydryer.service.type"
    _inherit = ["earlydryer.service.type", "pos.load.mixin"]

    @api.model
    def _load_pos_data_domain(self, data, config):
        if not config.earlydryer_enabled:
            return False
        return [("active", "=", True)]

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "id",
            "name",
            "code",
            "sequence",
            "standard_turnaround_hours",
            "express_available",
            "express_turnaround_hours",
            "express_surcharge_kind",
            "express_surcharge_value",
            "requires_tag",
        ]

    def _server_date_to_domain(self, domain):
        return domain
