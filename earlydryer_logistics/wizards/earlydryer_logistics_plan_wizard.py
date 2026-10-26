# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError

PARAM_MAX_STOPS = "earlydryer_logistics.max_stops_per_trip"
DEFAULT_MAX_STOPS = 12


class EarlydryerLogisticsPlanWizard(models.TransientModel):
    """Plan the day automatically (a draft the team then adjusts).

    1. the day's scheduled stops without trip are grouped by slot;
    2. inside a slot, zone by zone (zone sequence), into trips of at most N
       stops: a zone is kept on one trip unless it alone exceeds N;
    3. each trip is ordered by nearest neighbour from the plant using the GPS
       of the stops; stops without GPS follow, by zone sequence;
    4. riders are assigned round-robin among those selected.

    No road routing: straight-line distances only (see README).
    """

    _name = "earlydryer.logistics.plan.wizard"
    _description = "Earlydryer Plan Trips Automatically"

    date = fields.Date(required=True, default=fields.Date.context_today)
    branch_id = fields.Many2one(
        "earlydryer.branch",
        required=True,
        default=lambda self: self.env["earlydryer.logistics.stop"]._default_earlydryer_branch_id(),
    )
    rider_employee_ids = fields.Many2many("hr.employee", string="Available Riders")
    max_stops = fields.Integer(
        string="Max Stops per Trip",
        default=lambda self: self._default_max_stops(),
        required=True,
    )
    stop_count = fields.Integer(compute="_compute_stop_count")

    @api.model
    def _default_max_stops(self):
        value = self.env["ir.config_parameter"].sudo().get_param(PARAM_MAX_STOPS)
        try:
            return int(value) if value else DEFAULT_MAX_STOPS
        except ValueError:
            return DEFAULT_MAX_STOPS

    def _stops(self):
        self.ensure_one()
        return self.env["earlydryer.logistics.stop"].search(
            [
                ("earlydryer_branch_id", "=", self.branch_id.id),
                ("slot_date", "=", self.date),
                ("state", "=", "scheduled"),
                ("trip_id", "=", False),
            ]
        )

    @api.depends("date", "branch_id")
    def _compute_stop_count(self):
        for wizard in self:
            wizard.stop_count = len(wizard._stops()) if wizard.branch_id else 0

    # ------------------------------------------------------------------
    # Algorithm (plain functions of the records, easy to test or replace)
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_chunks(self, stops, max_stops):
        """``[[stops]]``: slot by slot, zone by zone, at most ``max_stops``."""
        max_stops = max(int(max_stops or 1), 1)
        chunks = []
        by_slot = {}
        for stop in stops:
            by_slot.setdefault((stop.slot_start, stop.slot_template_id.id), []).append(stop)
        for _slot, slot_stops in sorted(by_slot.items(), key=lambda item: (str(item[0][0]), item[0][1])):
            by_zone = {}
            for stop in slot_stops:
                by_zone.setdefault(stop.zone_id, []).append(stop)
            zones = sorted(
                by_zone, key=lambda zone: (not zone, zone.sequence, zone.id or 0)
            )
            current = []
            for zone in zones:
                zone_stops = by_zone[zone]
                if current and len(current) + len(zone_stops) > max_stops:
                    chunks.append(current)
                    current = []
                for stop in zone_stops:
                    if len(current) >= max_stops:
                        chunks.append(current)
                        current = []
                    current.append(stop)
            if current:
                chunks.append(current)
        return chunks

    @api.model
    def _earlydryer_order(self, stops, origin):
        """Nearest neighbour from ``origin`` (lat, lng) over the stops with
        GPS; the others follow by zone sequence."""
        Quote = self.env["earlydryer.logistics.quote"]
        with_gps = [s for s in stops if s.latitude or s.longitude]
        without = sorted(
            (s for s in stops if not (s.latitude or s.longitude)),
            key=lambda s: (s.zone_id.sequence if s.zone_id else 9999, s.id),
        )
        ordered = []
        position = origin
        remaining = list(with_gps)
        while remaining:
            if position:
                nearest = min(
                    remaining,
                    key=lambda s: (
                        Quote._earlydryer_haversine_km(position, (s.latitude, s.longitude)),
                        s.id,
                    ),
                )
            else:
                nearest = remaining[0]
            ordered.append(nearest)
            remaining.remove(nearest)
            position = (nearest.latitude, nearest.longitude)
        return ordered + without

    def action_plan(self):
        self.ensure_one()
        Stop = self.env["earlydryer.logistics.stop"]
        Stop._earlydryer_check_right("plan", self.branch_id)
        stops = self._stops()
        if not stops:
            raise UserError(self.env._("No scheduled stop without trip on that day."))
        Quote = self.env["earlydryer.logistics.quote"]
        origin = Quote._earlydryer_point(self.branch_id.partner_id)
        riders = self.rider_employee_ids
        Trip = self.env["earlydryer.logistics.trip"]
        trips = Trip
        for index, chunk in enumerate(self._earlydryer_chunks(stops, self.max_stops)):
            rider = riders[index % len(riders)] if riders else self.env["hr.employee"]
            first = chunk[0]
            trip = Trip.create(
                {
                    "earlydryer_branch_id": self.branch_id.id,
                    "date": self.date,
                    "slot": first.slot_template_id.name or False,
                    "rider_employee_id": rider.id,
                }
            )
            for sequence, stop in enumerate(self._earlydryer_order(chunk, origin), 1):
                stop.write({"trip_id": trip.id, "sequence": sequence * 10})
            trips |= trip
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_logistics.earlydryer_logistics_planning_action"
        )
        action["context"] = {
            "search_default_slot_date": fields.Date.to_string(self.date),
            "default_slot_date": fields.Date.to_string(self.date),
        }
        action["domain"] = [("slot_date", "=", self.date)]
        return action
