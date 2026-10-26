# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models


class EarlydryerGarmentCategory(models.Model):
    _name = "earlydryer.garment.category"
    _inherit = ["earlydryer.garment.category", "pos.load.mixin"]

    @api.model
    def _load_pos_data_domain(self, data, config):
        if not config.earlydryer_enabled:
            return False
        return [("active", "=", True)]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "code", "sequence", "garment_group", "piece_count"]

    def _server_date_to_domain(self, domain):
        # a handful of records: always reload them all (like pos_hr employees)
        return domain

    @api.model
    def _load_pos_data_read(self, records, config):
        read_records = super()._load_pos_data_read(records, config)
        # images as data URLs so the intake grid works offline
        images = {
            category.id: category.image_128.decode() if category.image_128 else False
            for category in records
        }
        for record in read_records:
            image = images.get(record["id"])
            record["_image"] = f"data:image/png;base64,{image}" if image else False
        return read_records
