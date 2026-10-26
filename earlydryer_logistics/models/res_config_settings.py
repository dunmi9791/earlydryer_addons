# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    earlydryer_logistics_road_factor = fields.Float(
        string="Road Factor",
        default=1.3,
        config_parameter="earlydryer_logistics.road_factor",
        help="Straight-line distance × this factor ≈ road distance (no routing "
        "service is used).",
    )
    earlydryer_logistics_gps_accuracy_m = fields.Float(
        string="GPS Accuracy Threshold (m)",
        default=100.0,
        config_parameter="earlydryer_logistics.gps_accuracy_m",
        help="Positions less accurate than this are flagged, never refused.",
    )
    earlydryer_logistics_max_stops = fields.Integer(
        string="Max Stops per Trip",
        default=12,
        config_parameter="earlydryer_logistics.max_stops_per_trip",
    )
    earlydryer_rider_short_mode = fields.Selection(
        related="company_id.earlydryer_rider_short_mode", readonly=False
    )
    earlydryer_rider_receivable_account_id = fields.Many2one(
        related="company_id.earlydryer_rider_receivable_account_id", readonly=False
    )
    earlydryer_carrier_expense_account_id = fields.Many2one(
        related="company_id.earlydryer_carrier_expense_account_id", readonly=False
    )
