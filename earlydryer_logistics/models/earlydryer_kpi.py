# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models
from odoo.exceptions import AccessError
from odoo.tools.translate import LazyTranslate

from odoo.addons.earlydryer_reporting.models.kpi import REGISTRY
from odoo.addons.earlydryer_reporting.tools import has_any, utc_bounds

_lt = LazyTranslate(__name__)

# earlydryer_reporting pattern: one REGISTRY entry and one private method each.
# code: label, unit, method, drill model, scope
LOGISTICS_KPIS = {
    "logistics_pickups_done": (
        _lt("Pickups done"),
        "stops",
        "_logistics_pickups_done",
        "earlydryer.logistics.stop",
        "logistics_done",
    ),
    "logistics_deliveries_done": (
        _lt("Deliveries done"),
        "stops",
        "_logistics_deliveries_done",
        "earlydryer.logistics.stop",
        "logistics_done",
    ),
    "logistics_on_slot_pct": (
        _lt("Done within the slot"),
        "percent",
        "_logistics_on_slot_pct",
        "earlydryer.logistics.stop",
        "logistics_done",
    ),
    "logistics_failed_pct": (
        _lt("Failed stops"),
        "percent",
        "_logistics_failed_pct",
        "earlydryer.logistics.stop",
        "logistics_failed",
    ),
    "logistics_stops_per_trip": (
        _lt("Stops per trip"),
        "stops",
        "_logistics_stops_per_trip",
        "earlydryer.logistics.trip",
        "logistics_trip",
    ),
    "logistics_fee_revenue": (
        _lt("Delivery fee revenue"),
        "currency",
        "_logistics_fee_revenue",
        "account.move.line",
        "logistics_fee",
    ),
    "logistics_cod_collected": (
        _lt("Cash collected at the door"),
        "currency",
        "_logistics_cod_collected",
        "earlydryer.logistics.stop",
        "logistics_done",
    ),
    "logistics_cash_difference": (
        _lt("Rider cash differences"),
        "currency",
        "_logistics_cash_difference",
        "earlydryer.logistics.trip",
        "logistics_trip",
    ),
    "logistics_carrier_cost": (
        _lt("3PL cost"),
        "currency",
        "_logistics_carrier_cost",
        "earlydryer.logistics.trip",
        "logistics_trip",
    ),
}
REGISTRY.update(LOGISTICS_KPIS)
# the dashboard's Logistics section: Operations Manager and above
LOGISTICS_GROUPS = ("group_operations_manager", "group_management", "group_admin")


class EarlydryerKpi(models.AbstractModel):
    _inherit = "earlydryer.kpi"

    @api.model
    def compute(
        self, codes, branch_ids, date_from, date_to, compare="previous", dashboard=False
    ):
        allowed = has_any(self.env, LOGISTICS_GROUPS)
        if codes and not allowed and set(codes) & set(LOGISTICS_KPIS):
            raise AccessError(
                self.env._("Logistics indicators are for Operations Managers.")
            )
        result = super().compute(
            codes, branch_ids, date_from, date_to, compare=compare, dashboard=dashboard
        )
        if not allowed:
            for code in LOGISTICS_KPIS:
                result.pop(code, None)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _logistics_split(self, branches, values):
        """``{"value", "breakdown"}`` of per-branch numbers ``{branch_id: x}``."""
        return {
            "value": float(sum(values.values())),
            "breakdown": [
                {
                    "branch_id": branch.id,
                    "name": branch.name,
                    "value": float(values.get(branch.id, 0.0)),
                }
                for branch in branches
            ],
        }

    def _logistics_ratio(self, branches, numerators, denominators, multiple=100.0):
        total = sum(denominators.values())
        return {
            "value": round(multiple * sum(numerators.values()) / total, 2)
            if total
            else 0.0,
            "breakdown": [
                {
                    "branch_id": branch.id,
                    "name": branch.name,
                    "value": round(
                        multiple
                        * numerators.get(branch.id, 0)
                        / denominators[branch.id],
                        2,
                    )
                    if denominators.get(branch.id)
                    else 0.0,
                }
                for branch in branches
            ],
        }

    def _logistics_stop_counts(self, branches, start, end, cache, extra):
        """``{branch_id: count}`` of stops done or failed in the period."""
        key = (
            "logistics_stops",
            tuple(branches.ids),
            start,
            end,
            tuple(map(tuple, extra)),
        )
        if key not in cache:
            utc_start, utc_end = utc_bounds(start, end)
            groups = (
                self.env["earlydryer.logistics.stop"]
                .sudo()
                ._read_group(
                    [
                        ("earlydryer_branch_id", "in", branches.ids),
                        ("done_on", ">=", utc_start),
                        ("done_on", "<", utc_end),
                        *extra,
                    ],
                    ["earlydryer_branch_id"],
                    ["__count"],
                )
            )
            cache[key] = {branch.id: count for branch, count in groups}
        return cache[key]

    def _logistics_stop_sum(self, branches, start, end, field, extra):
        utc_start, utc_end = utc_bounds(start, end)
        groups = (
            self.env["earlydryer.logistics.stop"]
            .sudo()
            ._read_group(
                [
                    ("earlydryer_branch_id", "in", branches.ids),
                    ("done_on", ">=", utc_start),
                    ("done_on", "<", utc_end),
                    *extra,
                ],
                ["earlydryer_branch_id"],
                [f"{field}:sum"],
            )
        )
        return {branch.id: total or 0.0 for branch, total in groups}

    def _logistics_trip_sums(self, branches, start, end, aggregates, extra=()):
        groups = (
            self.env["earlydryer.logistics.trip"]
            .sudo()
            ._read_group(
                [
                    ("earlydryer_branch_id", "in", branches.ids),
                    ("state", "=", "done"),
                    ("date", ">=", start),
                    ("date", "<=", end),
                    *extra,
                ],
                ["earlydryer_branch_id"],
                aggregates,
            )
        )
        return {branch.id: values for branch, *values in groups}

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------

    def _logistics_pickups_done(self, b, s, e, c):
        return self._logistics_split(
            b,
            self._logistics_stop_counts(
                b, s, e, c, [("stop_type", "=", "pickup"), ("state", "=", "done")]
            ),
        )

    def _logistics_deliveries_done(self, b, s, e, c):
        return self._logistics_split(
            b,
            self._logistics_stop_counts(
                b, s, e, c, [("stop_type", "=", "delivery"), ("state", "=", "done")]
            ),
        )

    def _logistics_on_slot_pct(self, b, s, e, c):
        done = self._logistics_stop_counts(
            b, s, e, c, [("state", "=", "done"), ("slot_start", "!=", False)]
        )
        on_slot = self._logistics_stop_counts(
            b, s, e, c, [("state", "=", "done"), ("on_slot", "=", True)]
        )
        return self._logistics_ratio(b, on_slot, done)

    def _logistics_failed_pct(self, b, s, e, c):
        closed = self._logistics_stop_counts(
            b, s, e, c, [("state", "in", ("done", "failed"))]
        )
        failed = self._logistics_stop_counts(b, s, e, c, [("state", "=", "failed")])
        result = self._logistics_ratio(b, failed, closed)
        utc_start, utc_end = utc_bounds(s, e)
        reasons = (
            self.env["earlydryer.logistics.stop"]
            .sudo()
            ._read_group(
                [
                    ("earlydryer_branch_id", "in", b.ids),
                    ("done_on", ">=", utc_start),
                    ("done_on", "<", utc_end),
                    ("state", "=", "failed"),
                ],
                ["fail_reason_id"],
                ["__count"],
                order="__count desc",
                limit=5,
            )
        )
        result["top_reasons"] = [
            {"name": reason.name or self.env._("Unknown"), "value": count}
            for reason, count in reasons
        ]
        return result

    def _logistics_stops_per_trip(self, b, s, e, c):
        sums = self._logistics_trip_sums(b, s, e, ["stop_count:sum", "__count"])
        stops = {branch_id: values[0] or 0 for branch_id, values in sums.items()}
        trips = {branch_id: values[1] for branch_id, values in sums.items()}
        return self._logistics_ratio(b, stops, trips, multiple=1.0)

    def _logistics_fee_revenue(self, b, s, e, c):
        """Fee lines of posted customer invoices (fee invoices, invoiced
        orders) and of POS orders not invoiced."""
        products = (
            self.env["product.product"]
            .sudo()
            .with_context(active_test=False)
            .search([("earlydryer_kind", "=", "delivery_fee")])
        )
        values = {}
        if products:
            for branch, balance in (
                self.env["account.move.line"]
                .sudo()
                ._read_group(
                    [
                        ("product_id", "in", products.ids),
                        ("parent_state", "=", "posted"),
                        ("move_id.move_type", "in", ("out_invoice", "out_refund")),
                        ("move_id.earlydryer_branch_id", "in", b.ids),
                        ("date", ">=", s),
                        ("date", "<=", e),
                    ],
                    ["move_id.earlydryer_branch_id"],
                    ["balance:sum"],
                )
            ):
                values[branch.id] = values.get(branch.id, 0.0) - (balance or 0.0)
            utc_start, utc_end = utc_bounds(s, e)
            for branch, subtotal in (
                self.env["pos.order.line"]
                .sudo()
                ._read_group(
                    [
                        ("product_id", "in", products.ids),
                        ("order_id.state", "in", ("paid", "done")),
                        ("order_id.account_move", "=", False),
                        ("order_id.config_id.earlydryer_branch_id", "in", b.ids),
                        ("order_id.date_order", ">=", utc_start),
                        ("order_id.date_order", "<", utc_end),
                    ],
                    ["order_id.config_id.earlydryer_branch_id"],
                    ["price_subtotal:sum"],
                )
            ):
                values[branch.id] = values.get(branch.id, 0.0) + (subtotal or 0.0)
        return self._logistics_split(b, values)

    def _logistics_cod_collected(self, b, s, e, c):
        return self._logistics_split(
            b,
            self._logistics_stop_sum(
                b,
                s,
                e,
                "cash_collected",
                [("state", "=", "done"), ("collection_method", "=", "cash")],
            ),
        )

    def _logistics_cash_difference(self, b, s, e, c):
        sums = self._logistics_trip_sums(b, s, e, ["cash_difference:sum"])
        return self._logistics_split(
            b, {branch_id: values[0] or 0.0 for branch_id, values in sums.items()}
        )

    def _logistics_carrier_cost(self, b, s, e, c):
        sums = self._logistics_trip_sums(
            b, s, e, ["carrier_fee:sum"], [("carrier_partner_id", "!=", False)]
        )
        return self._logistics_split(
            b, {branch_id: values[0] or 0.0 for branch_id, values in sums.items()}
        )

    # ------------------------------------------------------------------
    # Drill-down
    # ------------------------------------------------------------------

    def _drill(self, code, b, s, e, c):
        if code not in LOGISTICS_KPIS:
            return super()._drill(code, b, s, e, c)
        _label, _unit, _method, model, period = LOGISTICS_KPIS[code]
        utc_start, utc_end = (str(d) for d in utc_bounds(s, e))
        if period == "logistics_trip":
            domain = [
                ("earlydryer_branch_id", "in", b.ids),
                ("state", "=", "done"),
                ("date", ">=", str(s)),
                ("date", "<=", str(e)),
            ]
            if code == "logistics_carrier_cost":
                domain.append(("carrier_partner_id", "!=", False))
        elif period == "logistics_fee":
            domain = [
                ("product_id.earlydryer_kind", "=", "delivery_fee"),
                ("parent_state", "=", "posted"),
                ("move_id.earlydryer_branch_id", "in", b.ids),
                ("date", ">=", str(s)),
                ("date", "<=", str(e)),
            ]
        else:
            domain = [
                ("earlydryer_branch_id", "in", b.ids),
                ("done_on", ">=", utc_start),
                ("done_on", "<", utc_end),
                ("state", "=", "failed" if period == "logistics_failed" else "done"),
            ]
            if code == "logistics_pickups_done":
                domain.append(("stop_type", "=", "pickup"))
            elif code in ("logistics_deliveries_done", "logistics_cod_collected"):
                domain.append(("stop_type", "=", "delivery"))
        return {"model": model, "domain": domain, "context": {}}
