# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Earlydryer Plant",
        index=True,
        tracking=True,
        ondelete="restrict",
        help="Plant where this person works. Proposed first when recording who "
        "did the work on a laundry job stage.",
    )
