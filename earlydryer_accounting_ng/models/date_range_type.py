# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class DateRangeType(models.Model):
    _inherit = "date.range.type"

    earlydryer_period_type = fields.Boolean(
        string="Earlydryer Accounting Periods",
        help="Monthly periods created by the accounting setup (month-end close).",
    )
