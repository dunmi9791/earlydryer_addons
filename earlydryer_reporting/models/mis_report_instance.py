# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class MisReportInstance(models.Model):
    _inherit = "mis.report.instance"
    earlydryer_report_branch_ids = fields.Many2many(
        "earlydryer.branch", help="Scope of a generated Earlydryer report pack."
    )
