# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

from ..tools import dates, scope


class ProductivityWizard(models.TransientModel):
    _name = "earlydryer.productivity.wizard"
    _description = "Export Staff Productivity"
    branch_ids = fields.Many2many("earlydryer.branch")
    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(required=True, default=fields.Date.context_today)

    def action_export(self):
        self.ensure_one()
        dates(self.date_from, self.date_to)
        branches = scope(self.env, self.branch_ids.ids, staff=True)
        return self.env.ref(
            "earlydryer_reporting.action_productivity_xlsx"
        ).report_action(
            self,
            data={
                "branch_ids": branches.ids,
                "date_from": str(self.date_from),
                "date_to": str(self.date_to),
            },
        )
