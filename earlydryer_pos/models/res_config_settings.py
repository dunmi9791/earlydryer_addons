# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_earlydryer_branch_id = fields.Many2one(
        related="pos_config_id.earlydryer_branch_id", readonly=False
    )
    pos_earlydryer_enabled = fields.Boolean(
        related="pos_config_id.earlydryer_enabled", readonly=False
    )
    pos_earlydryer_walkin_partner_id = fields.Many2one(
        related="pos_config_id.earlydryer_walkin_partner_id", readonly=False
    )
    pos_earlydryer_tag_range_size = fields.Integer(
        related="pos_config_id.earlydryer_tag_range_size", readonly=False
    )
    pos_earlydryer_tag_range_low_pct = fields.Integer(
        related="pos_config_id.earlydryer_tag_range_low_pct", readonly=False
    )
    pos_earlydryer_label_width_mm = fields.Float(
        related="pos_config_id.earlydryer_label_width_mm", readonly=False
    )
    pos_earlydryer_label_height_mm = fields.Float(
        related="pos_config_id.earlydryer_label_height_mm", readonly=False
    )
    pos_earlydryer_print_tags_auto = fields.Boolean(
        related="pos_config_id.earlydryer_print_tags_auto", readonly=False
    )
    pos_earlydryer_receipt_terms = fields.Text(
        related="pos_config_id.earlydryer_receipt_terms", readonly=False
    )
    pos_earlydryer_collection_cache_days = fields.Integer(
        related="pos_config_id.earlydryer_collection_cache_days", readonly=False
    )
