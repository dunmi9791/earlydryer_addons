# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class EarlydryerLogisticsCloseWizard(models.TransientModel):
    """End of the day: count the rider's cash and close the trip."""

    _name = "earlydryer.logistics.close.wizard"
    _description = "Earlydryer Close Trip"

    trip_id = fields.Many2one("earlydryer.logistics.trip", required=True)
    currency_id = fields.Many2one(related="trip_id.currency_id")
    rider_employee_id = fields.Many2one(related="trip_id.rider_employee_id")
    cash_expected = fields.Monetary(related="trip_id.cash_expected")
    cash_counted = fields.Monetary(required=True)
    difference = fields.Monetary(compute="_compute_difference")
    short_mode = fields.Selection(related="trip_id.company_id.earlydryer_rider_short_mode")
    has_vehicle = fields.Boolean(compute="_compute_difference")
    odometer_start = fields.Float(related="trip_id.odometer_start")
    odometer_end = fields.Float()
    note = fields.Text()

    @api.depends("cash_counted", "cash_expected", "trip_id")
    def _compute_difference(self):
        for wizard in self:
            wizard.difference = wizard.cash_counted - wizard.cash_expected
            wizard.has_vehicle = bool(wizard.trip_id.vehicle_id)

    @api.onchange("trip_id")
    def _onchange_trip_id(self):
        self.cash_counted = self.trip_id.cash_expected

    def action_confirm(self):
        self.ensure_one()
        self.trip_id._earlydryer_close(
            self.cash_counted, odometer_end=self.odometer_end or None, note=self.note
        )
        return {"type": "ir.actions.act_window_close"}
