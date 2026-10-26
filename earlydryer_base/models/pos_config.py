# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        index=True,
        check_company=True,
        ondelete="restrict",
    )
