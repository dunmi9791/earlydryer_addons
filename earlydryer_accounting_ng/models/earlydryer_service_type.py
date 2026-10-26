# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

SERVICE_LINE_DOMAIN = [
    ("plan_id", "=", "earlydryer_accounting_ng.analytic_plan_service_lines")
]


class EarlydryerServiceType(models.Model):
    _inherit = "earlydryer.service.type"

    earlydryer_service_line_id = fields.Many2one(
        "account.analytic.account",
        string="Service Line",
        ondelete="restrict",
        domain=lambda self: self._earlydryer_service_line_domain(),
        help="Analytic account of the service line revenue of this service "
        "type is reported on (P&L by service line).",
    )

    def _earlydryer_service_line_domain(self):
        plan = self.env.ref(
            "earlydryer_accounting_ng.analytic_plan_service_lines",
            raise_if_not_found=False,
        )
        return [("plan_id", "=", plan.id)] if plan else []
