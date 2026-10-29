# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    earlydryer_is_rider = fields.Boolean(
        string="Rider",
        help="Delivers for Earlydryer. A rider without a login is put on trips "
        "by the office, which records the outcomes.",
    )


class HrEmployeePublic(models.Model):
    _inherit = "hr.employee.public"

    # users without HR rights pick riders through this SQL view
    earlydryer_is_rider = fields.Boolean(string="Rider", readonly=True)
