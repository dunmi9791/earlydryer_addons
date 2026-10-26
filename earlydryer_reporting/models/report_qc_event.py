# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ReportQcEvent(models.Model):
    _name = "earlydryer.report.qc.event"
    _description = "Earlydryer QC Reporting History"
    item_id = fields.Many2one(
        "laundry.job.item", required=True, ondelete="cascade", index=True
    )
    earlydryer_branch_id = fields.Many2one(
        related="item_id.earlydryer_branch_id", store=True, index=True
    )
    company_id = fields.Many2one(related="item_id.company_id", store=True)
    result = fields.Selection(
        [
            ("failed", "Failed"),
            ("passed", "Passed"),
            ("missing", "Missing"),
            ("found", "Found"),
        ],
        required=True,
    )
    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
