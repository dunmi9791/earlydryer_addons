# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_earlydryer_branch_id = fields.Many2one(
        related="pos_config_id.earlydryer_branch_id",
        readonly=False,
    )
