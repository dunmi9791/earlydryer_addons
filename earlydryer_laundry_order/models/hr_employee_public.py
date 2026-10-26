# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class HrEmployeePublic(models.Model):
    _inherit = "hr.employee.public"

    # Users without HR rights search hr.employee through this SQL view (the
    # stage-move employee picker): the stored column is copied by the view.
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch", string="Earlydryer Plant", readonly=True
    )
