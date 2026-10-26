# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import AccessError


class EarlydryerLogisticsDashboard(models.TransientModel):
    """Logistics section of the dashboard (Operations Manager and above)."""

    _name = "earlydryer.logistics.dashboard"
    _description = "Earlydryer Logistics Dashboard"

    date_from = fields.Date(
        required=True, default=lambda self: fields.Date.context_today(self).replace(day=1)
    )
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    branch_ids = fields.Many2many("earlydryer.branch", string="Plants")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )
    pickups_done = fields.Integer(compute="_compute_kpis")
    deliveries_done = fields.Integer(compute="_compute_kpis")
    on_slot_rate = fields.Float(string="On-slot rate (%)", compute="_compute_kpis")
    failed_rate = fields.Float(string="Failed rate (%)", compute="_compute_kpis")
    avg_stops_per_trip = fields.Float(compute="_compute_kpis")
    delivery_fee_revenue = fields.Monetary(compute="_compute_kpis")
    cod_collected = fields.Monetary(string="COD collected", compute="_compute_kpis")
    rider_cash_difference = fields.Monetary(compute="_compute_kpis")
    carrier_cost = fields.Monetary(string="3PL cost", compute="_compute_kpis")
    top_fail_reasons = fields.Html(compute="_compute_kpis", sanitize=True)

    @api.model
    def _check_access_dashboard(self):
        if not (
            self.env.su
            or self.env.user.has_group("earlydryer_base.group_operations_manager")
        ):
            raise AccessError(
                self.env._("The logistics dashboard is for Operations Managers.")
            )

    @api.depends("date_from", "date_to", "branch_ids")
    def _compute_kpis(self):
        self._check_access_dashboard()
        Kpi = self.env["earlydryer.logistics.kpi"]
        for board in self:
            values = Kpi.compute_kpis(
                board.date_from or fields.Date.context_today(self),
                board.date_to or fields.Date.context_today(self),
                board.branch_ids.ids,
            )
            reasons = values.pop("top_fail_reasons")
            board.update(values)
            rows = Markup("").join(
                Markup("<li>%s: %s</li>") % (escape(name), count)
                for name, count in reasons
            )
            board.top_fail_reasons = (
                Markup("<ul>%s</ul>") % rows if reasons else self.env._("No failures")
            )

    def action_refresh(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }
