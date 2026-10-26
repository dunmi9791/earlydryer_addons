# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    earlydryer_kind = fields.Selection(
        selection_add=[("settlement", "Balance Settlement")],
        ondelete={"settlement": "set null"},
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        return [
            *fields_list,
            "earlydryer_kind",
            "earlydryer_garment_category_id",
            "earlydryer_service_type_id",
            "earlydryer_turnaround_hours",
            "earlydryer_express_turnaround_hours",
        ]
