# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time, timedelta

from odoo import api, fields, models


class EarlydryerLogisticsKpi(models.AbstractModel):
    """Logistics KPIs: one method per KPI plus one registry entry each.

    ``earlydryer_reporting`` (the KPI registry and dashboard of the build
    prompt) is not installed: ``_earlydryer_kpi_registry()`` returns the
    entries in the shape such a registry takes (code, name, section, method,
    unit, groups) and the *Logistics Dashboard* of this module reads them.
    Each method takes ``(date_from, date_to, branches)`` and returns a number
    (or, for top reasons, a list of ``(name, count)``).
    """

    _name = "earlydryer.logistics.kpi"
    _description = "Earlydryer Logistics KPIs"

    SECTION = "logistics"
    GROUPS = "earlydryer_base.group_operations_manager"

    @api.model
    def _earlydryer_kpi_registry(self):
        _ = self.env._
        entries = [
            ("pickups_done", _("Pickups done"), "count"),
            ("deliveries_done", _("Deliveries done"), "count"),
            ("on_slot_rate", _("On-slot rate"), "percent"),
            ("failed_rate", _("Failed rate"), "percent"),
            ("top_fail_reasons", _("Top failure reasons"), "list"),
            ("avg_stops_per_trip", _("Average stops per trip"), "number"),
            ("delivery_fee_revenue", _("Delivery fee revenue"), "amount"),
            ("cod_collected", _("Cash collected at the door"), "amount"),
            ("rider_cash_difference", _("Rider cash differences"), "amount"),
            ("carrier_cost", _("3PL cost"), "amount"),
        ]
        return [
            {
                "code": code,
                "name": name,
                "section": self.SECTION,
                "model": self._name,
                "method": f"_kpi_{code}",
                "unit": unit,
                "groups": self.GROUPS,
            }
            for code, name, unit in entries
        ]

    @api.model
    def compute_kpis(self, date_from, date_to, branch_ids=None):
        """``{code: value}`` of every logistics KPI between two dates
        (included) on the given plants (default: the user's plants)."""
        branches = self._branches(branch_ids)
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        return {
            entry["code"]: getattr(self, entry["method"])(date_from, date_to, branches)
            for entry in self._earlydryer_kpi_registry()
        }

    @api.model
    def _branches(self, branch_ids=None):
        allowed = self.env.user._earlydryer_allowed_branches()
        if branch_ids:
            return allowed & self.env["earlydryer.branch"].browse(branch_ids)
        return allowed

    @api.model
    def _bounds(self, date_from, date_to):
        return (
            datetime.combine(date_from, time.min),
            datetime.combine(date_to + timedelta(days=1), time.min),
        )

    @api.model
    def _stops(self, date_from, date_to, branches, extra=None):
        start, end = self._bounds(date_from, date_to)
        domain = [
            ("earlydryer_branch_id", "in", branches.ids),
            ("done_on", ">=", start),
            ("done_on", "<", end),
        ] + (extra or [])
        return self.env["earlydryer.logistics.stop"].sudo().search(domain)

    @api.model
    def _trips(self, date_from, date_to, branches, extra=None):
        domain = [
            ("earlydryer_branch_id", "in", branches.ids),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("state", "=", "done"),
        ] + (extra or [])
        return self.env["earlydryer.logistics.trip"].sudo().search(domain)

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------

    @api.model
    def _kpi_pickups_done(self, date_from, date_to, branches):
        return len(
            self._stops(
                date_from, date_to, branches,
                [("stop_type", "=", "pickup"), ("state", "=", "done")],
            )
        )

    @api.model
    def _kpi_deliveries_done(self, date_from, date_to, branches):
        return len(
            self._stops(
                date_from, date_to, branches,
                [("stop_type", "=", "delivery"), ("state", "=", "done")],
            )
        )

    @api.model
    def _kpi_on_slot_rate(self, date_from, date_to, branches):
        done = self._stops(
            date_from, date_to, branches,
            [("state", "=", "done"), ("slot_start", "!=", False)],
        )
        if not done:
            return 0.0
        return round(100.0 * len(done.filtered("on_slot")) / len(done), 1)

    @api.model
    def _kpi_failed_rate(self, date_from, date_to, branches):
        stops = self._stops(
            date_from, date_to, branches, [("state", "in", ("done", "failed"))]
        )
        if not stops:
            return 0.0
        failed = stops.filtered(lambda s: s.state == "failed")
        return round(100.0 * len(failed) / len(stops), 1)

    @api.model
    def _kpi_top_fail_reasons(self, date_from, date_to, branches, limit=5):
        failed = self._stops(date_from, date_to, branches, [("state", "=", "failed")])
        counts = {}
        for stop in failed:
            name = stop.fail_reason_id.name or self.env._("Unknown")
            counts[name] = counts.get(name, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]

    @api.model
    def _kpi_avg_stops_per_trip(self, date_from, date_to, branches):
        trips = self._trips(date_from, date_to, branches)
        if not trips:
            return 0.0
        return round(sum(trips.mapped("stop_count")) / len(trips), 1)

    @api.model
    def _kpi_delivery_fee_revenue(self, date_from, date_to, branches):
        """Fee lines of posted invoices (fee invoices and invoiced orders) and
        of paid POS orders of the plants."""
        products = self.env["product.product"].sudo().search(
            [("earlydryer_kind", "=", "delivery_fee")]
        )
        if not products:
            return 0.0
        lines = self.env["account.move.line"].sudo().search(
            [
                ("product_id", "in", products.ids),
                ("parent_state", "=", "posted"),
                ("move_id.move_type", "in", ("out_invoice", "out_refund")),
                ("move_id.earlydryer_branch_id", "in", branches.ids),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
            ]
        )
        revenue = -sum(lines.mapped("balance"))
        start, end = self._bounds(date_from, date_to)
        pos_lines = self.env["pos.order.line"].sudo().search(
            [
                ("product_id", "in", products.ids),
                ("order_id.state", "in", ("paid", "done")),
                ("order_id.account_move", "=", False),
                ("order_id.config_id.earlydryer_branch_id", "in", branches.ids),
                ("order_id.date_order", ">=", start),
                ("order_id.date_order", "<", end),
            ]
        )
        return revenue + sum(pos_lines.mapped("price_subtotal"))

    @api.model
    def _kpi_cod_collected(self, date_from, date_to, branches):
        stops = self._stops(
            date_from, date_to, branches,
            [("state", "=", "done"), ("collection_method", "=", "cash")],
        )
        return sum(stops.mapped("cash_collected"))

    @api.model
    def _kpi_rider_cash_difference(self, date_from, date_to, branches):
        return sum(self._trips(date_from, date_to, branches).mapped("cash_difference"))

    @api.model
    def _kpi_carrier_cost(self, date_from, date_to, branches):
        trips = self._trips(
            date_from, date_to, branches, [("carrier_partner_id", "!=", False)]
        )
        return sum(trips.mapped("carrier_fee"))
