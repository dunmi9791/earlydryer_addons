# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models


class EarlydryerSurcharge(models.Model):
    _name = "earlydryer.surcharge"
    _inherit = ["earlydryer.surcharge", "pos.load.mixin"]

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
            "kind",
            "compute_mode",
            "percent",
            "product_id",
            "service_type_ids",
            "category_ids",
        ]

    def _server_date_to_domain(self, domain):
        return domain
