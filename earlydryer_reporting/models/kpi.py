# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL
from odoo.tools.translate import LazyTranslate

from ..tools import (
    DASHBOARD_GROUPS,
    LAGOS,
    STAFF_GROUPS,
    dates,
    has_any,
    scope,
    utc_bounds,
)

# Lazy labels are extracted for translation without requiring an environment at import.
_lt = LazyTranslate(__name__)

# code: label, unit, method, drill model, scope (period/now/ready/stage)
REGISTRY = {
    "orders_count": (
        _lt("Orders received"),
        "orders",
        "_orders_count",
        "job",
        "period",
    ),
    "orders_value": (_lt("Orders taken"), "currency", "_orders_value", "job", "period"),
    "items_count": (
        _lt("Garments received"),
        "items",
        "_items_count",
        "item",
        "period",
    ),
    "avg_order_value": (
        _lt("Average order value"),
        "currency",
        "_avg_order_value",
        "job",
        "period",
    ),
    "retail_sales": (
        _lt("Retail sales"),
        "currency",
        "_retail_sales",
        "sales",
        "period",
    ),
    "revenue_posted": (
        _lt("Posted revenue"),
        "currency",
        "_revenue_posted",
        "account.move.line",
        "account",
    ),
    "collected_count": (
        _lt("Orders collected"),
        "orders",
        "_collected_count",
        "stage",
        "stage",
    ),
    "delivered_count": (
        _lt("Orders delivered"),
        "orders",
        "_delivered_count",
        "stage",
        "stage",
    ),
    "turnaround_avg_h": (
        _lt("Average turnaround"),
        "hours",
        "_turnaround_avg_h",
        "job",
        "ready",
    ),
    "turnaround_p90_h": (
        _lt("90th percentile turnaround"),
        "hours",
        "_turnaround_p90_h",
        "job",
        "ready",
    ),
    "on_time_pct": (_lt("On time"), "percent", "_on_time_pct", "job", "ready"),
    "overdue_count": (_lt("Overdue now"), "orders", "_overdue_count", "job", "now"),
    "ready_uncollected_count": (
        _lt("Ready for collection now"),
        "orders",
        "_ready_uncollected_count",
        "job",
        "now",
    ),
    "uncollected_count": (
        _lt("Became uncollected"),
        "orders",
        "_uncollected_count",
        "stage",
        "stage",
    ),
    "unpaid_balance": (
        _lt("Unpaid job balances now"),
        "currency",
        "_unpaid_balance",
        "job",
        "now",
    ),
    "unpaid_releases": (
        _lt("Released unpaid"),
        "orders",
        "_unpaid_releases",
        "stage",
        "stage",
    ),
    "discount_value": (
        _lt("Discounts"),
        "currency",
        "_discount_value",
        "discount",
        "period",
    ),
    "discount_pct": (
        _lt("Discounts / gross"),
        "percent",
        "_discount_pct",
        "discount",
        "period",
    ),
    "new_customers": (
        _lt("New customers"),
        "customers",
        "_new_customers",
        "job",
        "period",
    ),
    "repeat_customers": (
        _lt("Repeat customers"),
        "customers",
        "_repeat_customers",
        "job",
        "period",
    ),
    "repeat_rate": (
        _lt("Repeat order rate"),
        "percent",
        "_repeat_rate",
        "job",
        "period",
    ),
    "wallet_topups": (
        _lt("Wallet top-ups"),
        "currency",
        "_wallet_topups",
        "earlydryer.wallet.transaction",
        "wallet",
    ),
    "wallet_balance": (
        _lt("Wallet balance now"),
        "currency",
        "_wallet_balance",
        "earlydryer.wallet.transaction",
        "now",
    ),
    "expenses": (
        _lt("Expenses"),
        "currency",
        "_expenses",
        "account.move.line",
        "account",
    ),
    "cost_per_kg": (
        _lt("Direct cost per kg"),
        "currency/kg",
        "_cost_per_kg",
        "item",
        "ready",
    ),
    "rework_rate": (
        _lt("QC rework rate"),
        "percent",
        "_rework_rate",
        "earlydryer.report.qc.event",
        "qc",
    ),
    "missing_items": (
        _lt("Items flagged missing"),
        "items",
        "_missing_items",
        "item",
        "missing",
    ),
    "productivity": (
        _lt("Staff productivity"),
        "items",
        "_productivity",
        "stage",
        "stage",
    ),
}


class Kpi(models.AbstractModel):
    _name = "earlydryer.kpi"
    _description = "Earlydryer KPI Service"

    @api.model
    def compute(
        self, codes, branch_ids, date_from, date_to, compare="previous", dashboard=False
    ):
        if dashboard and not has_any(self.env, DASHBOARD_GROUPS):
            raise AccessError(self.env._("You do not have access to the dashboard."))
        # LLVM JIT startup dominates these short interactive aggregates on larger views.
        # Transaction-local only: no database/server configuration is changed.
        self.env.cr.execute(SQL("SET LOCAL jit = off"))
        staff_only = not has_any(self.env, DASHBOARD_GROUPS) and has_any(
            self.env, STAFF_GROUPS
        )
        requested = list(
            dict.fromkeys(
                codes
                or (
                    ["productivity"]
                    if staff_only
                    else [
                        c
                        for c in REGISTRY
                        if c != "productivity" or has_any(self.env, STAFF_GROUPS)
                    ]
                )
            )
        )
        if any(c not in REGISTRY for c in requested):
            raise ValidationError(self.env._("Unknown KPI."))
        if staff_only and any(c != "productivity" for c in requested):
            raise AccessError(self.env._("HR has access to productivity only."))
        if "productivity" in requested and not has_any(self.env, STAFF_GROUPS):
            raise AccessError(self.env._("Staff performance data is restricted."))
        branches = scope(self.env, branch_ids, staff=staff_only)
        start, end, previous = dates(date_from, date_to, compare)
        cache = {"_periods": [(start, end), previous]}
        result = {}
        for code in requested:
            label, unit, method, _model, period = REGISTRY[code]
            current = getattr(self, method)(branches, start, end, cache)
            before = (
                current
                if period == "now"
                else getattr(self, method)(branches, *previous, cache)
            )
            value = current.get("value", 0)
            previous_value = before.get("value", 0)
            domain = self._drill(code, branches, start, end, cache)
            result[code] = dict(
                current,
                value=round(float(value), 4),
                compare_value=round(float(previous_value), 4),
                delta_pct=(
                    round((value - previous_value) / abs(previous_value) * 100, 2)
                    if previous_value
                    else None
                ),
                unit=unit,
                label=str(label),
                point_in_time=period == "now",
                currency=(
                    branches.company_id.currency_id or self.env.company.currency_id
                ).name,
                drill=domain,
            )
        if not codes:
            result["_meta"] = self._dashboard_meta(
                branches, start, end, cache, staff_only
            )
        return result

    def _query(self, cache, key, sql):
        if key not in cache:
            self.env.flush_all()
            self.env.cr.execute(sql)
            cache[key] = self.env.cr.dictfetchall()
        return cache[key]

    def _jobs(self, branches, start, end, cache):
        periods = cache.get("_periods", [(start, end), (start, end)])
        rows = self._query(
            cache,
            ("jobs-both", tuple(branches.ids)),
            SQL(
                """
            WITH bounds(period,date_from,date_to) AS (VALUES(0,%s::date,%s::date),(1,%s::date,%s::date))
            SELECT bounds.period,earlydryer_branch_id,
            count(*) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to) orders_count,
            coalesce(sum(amount_total) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to),0) orders_value,
            coalesce(sum(item_count) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to),0) items_count,
            coalesce(avg(turnaround_hours) FILTER(WHERE ready_date BETWEEN bounds.date_from AND bounds.date_to),0) turnaround_avg_h,
            coalesce(percentile_cont(0.9) WITHIN GROUP(ORDER BY turnaround_hours) FILTER(WHERE ready_date BETWEEN bounds.date_from AND bounds.date_to),0) turnaround_p90_h,
            count(*) FILTER(WHERE ready_date BETWEEN bounds.date_from AND bounds.date_to AND on_time) on_time_count,
            count(*) FILTER(WHERE ready_date BETWEEN bounds.date_from AND bounds.date_to) ready_count,
            count(*) FILTER(WHERE is_overdue) overdue_count,
            count(*) FILTER(WHERE state='ready') ready_uncollected_count,
            count(DISTINCT partner_id) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to AND first_received_date BETWEEN bounds.date_from AND bounds.date_to) new_customers,
            array_agg(DISTINCT partner_id) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to AND first_received_date BETWEEN bounds.date_from AND bounds.date_to) new_partner_ids,
            count(DISTINCT partner_id) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to AND first_received_date<bounds.date_from) repeat_customers,
            array_agg(DISTINCT partner_id) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to AND first_received_date<bounds.date_from) repeat_partner_ids,
            array_agg(id) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to AND first_received_date<bounds.date_from) repeat_job_ids,
            count(*) FILTER(WHERE received_date BETWEEN bounds.date_from AND bounds.date_to AND first_received_date<bounds.date_from) repeat_orders
            FROM earlydryer_report_job CROSS JOIN bounds WHERE earlydryer_branch_id=ANY(%s)
            GROUP BY GROUPING SETS ((bounds.period,earlydryer_branch_id),(bounds.period))
        """,
                periods[0][0],
                periods[0][1],
                periods[1][0],
                periods[1][1],
                branches.ids,
            ),
        )
        period = 0 if (start, end) == tuple(periods[0]) else 1
        return [row for row in rows if row["period"] == period]

    def _value(self, rows, key, branches):
        total = next(
            (
                row.get(key, 0) or 0
                for row in rows
                if row.get("earlydryer_branch_id") is None
            ),
            0,
        )
        return {
            "value": float(total),
            "breakdown": [
                {
                    "branch_id": row["earlydryer_branch_id"],
                    "name": branches.browse(row["earlydryer_branch_id"]).name,
                    "value": float(row.get(key, 0) or 0),
                }
                for row in rows
                if row.get("earlydryer_branch_id")
            ],
        }

    def _job_value(self, key, b, s, e, c):
        return self._value(self._jobs(b, s, e, c), key, b)

    def _orders_count(self, b, s, e, c):
        return self._job_value("orders_count", b, s, e, c)

    def _orders_value(self, b, s, e, c):
        return self._job_value("orders_value", b, s, e, c)

    def _items_count(self, b, s, e, c):
        return self._job_value("items_count", b, s, e, c)

    def _turnaround_avg_h(self, b, s, e, c):
        result = self._job_value("turnaround_avg_h", b, s, e, c)
        result["service_breakdown"] = self._turnaround_services(b, s, e, c)
        return result

    def _turnaround_p90_h(self, b, s, e, c):
        result = self._job_value("turnaround_p90_h", b, s, e, c)
        result["service_breakdown"] = self._turnaround_services(b, s, e, c)
        return result

    def _overdue_count(self, b, s, e, c):
        return self._job_value("overdue_count", b, s, e, c)

    def _ready_uncollected_count(self, b, s, e, c):
        return self._job_value("ready_uncollected_count", b, s, e, c)

    def _new_customers(self, b, s, e, c):
        return self._job_value("new_customers", b, s, e, c)

    def _repeat_customers(self, b, s, e, c):
        return self._job_value("repeat_customers", b, s, e, c)

    def _ratio(self, rows, numerator, denominator, b, multiple=100):
        return self._value(
            [
                dict(
                    row,
                    ratio=(
                        row[numerator] / row[denominator] * multiple
                        if row[denominator]
                        else 0
                    ),
                )
                for row in rows
            ],
            "ratio",
            b,
        )

    def _avg_order_value(self, b, s, e, c):
        return self._ratio(self._jobs(b, s, e, c), "orders_value", "orders_count", b, 1)

    def _on_time_pct(self, b, s, e, c):
        return self._ratio(self._jobs(b, s, e, c), "on_time_count", "ready_count", b)

    def _repeat_rate(self, b, s, e, c):
        return self._ratio(self._jobs(b, s, e, c), "repeat_orders", "orders_count", b)

    def _retail_sales(self, b, s, e, c):
        rows = self._query(
            c,
            ("retail", tuple(b.ids), s, e),
            SQL(
                "SELECT earlydryer_branch_id,coalesce(sum(net),0) amount FROM earlydryer_report_sales WHERE earlydryer_branch_id=ANY(%s) AND date BETWEEN %s AND %s AND product_kind='retail' GROUP BY GROUPING SETS ((earlydryer_branch_id),())",
                b.ids,
                s,
                e,
            ),
        )
        return self._value(rows, "amount", b)

    def _stage_totals(self, b, s, e, c):
        start, end = utc_bounds(s, e)
        return self._query(
            c,
            ("stage", tuple(b.ids), s, e),
            SQL(
                """SELECT earlydryer_branch_id,count(DISTINCT job_id) FILTER(WHERE to_state='collected') collected_count,
   count(DISTINCT job_id) FILTER(WHERE to_state='delivered') delivered_count,count(DISTINCT job_id) FILTER(WHERE to_state='uncollected') uncollected_count,
   count(DISTINCT job_id) FILTER(WHERE to_state IN ('collected','delivered','out_for_delivery') AND earlydryer_release_unpaid) unpaid_releases
   FROM earlydryer_report_stage WHERE earlydryer_branch_id=ANY(%s) AND date>=%s AND date<%s GROUP BY GROUPING SETS ((earlydryer_branch_id),())""",
                b.ids,
                start,
                end,
            ),
        )

    def _collected_count(self, b, s, e, c):
        return self._value(self._stage_totals(b, s, e, c), "collected_count", b)

    def _delivered_count(self, b, s, e, c):
        return self._value(self._stage_totals(b, s, e, c), "delivered_count", b)

    def _uncollected_count(self, b, s, e, c):
        return self._value(self._stage_totals(b, s, e, c), "uncollected_count", b)

    def _unpaid_releases(self, b, s, e, c):
        return self._value(self._stage_totals(b, s, e, c), "unpaid_releases", b)

    def _discounts(self, b, s, e, c):
        return self._query(
            c,
            ("discount", tuple(b.ids), s, e),
            SQL(
                "SELECT earlydryer_branch_id,coalesce(sum(gross),0) gross,coalesce(sum(discount),0) discount FROM earlydryer_report_discount WHERE earlydryer_branch_id=ANY(%s) AND date BETWEEN %s AND %s GROUP BY GROUPING SETS ((earlydryer_branch_id),())",
                b.ids,
                s,
                e,
            ),
        )

    def _discount_value(self, b, s, e, c):
        result = self._value(self._discounts(b, s, e, c), "discount", b)
        start, end = utc_bounds(s, e)
        result["approved_count"] = self._query(
            c,
            ("approval", tuple(b.ids), s, e),
            SQL(
                "SELECT count(*) count FROM earlydryer_approval_request WHERE earlydryer_branch_id=ANY(%s) AND approval_type='discount' AND state='approved' AND decided_on>=%s AND decided_on<%s",
                b.ids,
                start,
                end,
            ),
        )[0]["count"]
        return result

    def _discount_pct(self, b, s, e, c):
        return self._ratio(self._discounts(b, s, e, c), "discount", "gross", b)

    def _financial(self, b, s, e, c):
        return self._query(
            c,
            ("financial", tuple(b.ids), s, e),
            SQL(
                "SELECT earlydryer_branch_id,account_type,account_id,account_name account,sum(balance) balance FROM earlydryer_report_ledger WHERE earlydryer_branch_id=ANY(%s) AND date BETWEEN %s AND %s GROUP BY earlydryer_branch_id,account_type,account_id,account_name",
                b.ids,
                s,
                e,
            ),
        )

    def _financial_value(self, b, s, e, c, income=False):
        rows = self._financial(b, s, e, c)
        wanted = [
            row
            for row in rows
            if (row["account_type"] in ("income", "income_other")) == income
        ]
        sign = -1 if income else 1
        accounts = {}
        for row in wanted:
            entry = accounts.setdefault(
                row["account_id"],
                {
                    "account_id": row["account_id"],
                    "name": row["account"],
                    "value": 0.0,
                    "branch_id": False,
                },
            )
            entry["value"] += float(row["balance"]) * sign
        return {
            "value": sum(float(row["balance"]) * sign for row in wanted),
            "breakdown": [
                {
                    "branch_id": branch.id,
                    "name": branch.name,
                    "value": sum(
                        float(x["balance"]) * sign
                        for x in wanted
                        if x["earlydryer_branch_id"] == branch.id
                    ),
                }
                for branch in b
            ],
            "accounts": sorted(
                accounts.values(), key=lambda row: row["value"], reverse=True
            )[:5],
        }

    def _revenue_posted(self, b, s, e, c):
        return self._financial_value(b, s, e, c, True)

    def _expenses(self, b, s, e, c):
        return self._financial_value(b, s, e, c)

    def _wallet_topups(self, b, s, e, c):
        start, end = utc_bounds(s, e)
        rows = self._query(
            c,
            ("wallet_topups", tuple(b.ids), s, e),
            SQL(
                "SELECT earlydryer_branch_id,coalesce(sum(amount),0) amount FROM earlydryer_wallet_transaction WHERE earlydryer_branch_id=ANY(%s) AND state='posted' AND type='topup' AND date>=%s AND date<%s GROUP BY GROUPING SETS ((earlydryer_branch_id),())",
                b.ids,
                start,
                end,
            ),
        )
        return self._value(rows, "amount", b)

    def _wallet_balance(self, b, s, e, c):
        # Attribute each signed transaction to its plant. Unattributed historical balances
        # are returned only when the complete company plant scope is selected.
        all_branches = self.env["earlydryer.branch"].search(
            [("company_id", "in", b.company_id.ids)]
        )
        include_unassigned = bool(b and set(all_branches.ids) <= set(b.ids))
        rows = self._query(
            c,
            ("wallet_balance", tuple(b.ids)),
            SQL(
                "SELECT earlydryer_branch_id,coalesce(sum(signed_amount),0) amount FROM earlydryer_wallet_transaction WHERE state='posted' AND (earlydryer_branch_id=ANY(%s) OR (earlydryer_branch_id IS NULL AND company_id=ANY(%s) AND %s)) GROUP BY earlydryer_branch_id",
                b.ids,
                b.company_id.ids,
                include_unassigned,
            ),
        )
        return {
            "value": sum(float(x["amount"]) for x in rows),
            "breakdown": [
                {"branch_id": x["earlydryer_branch_id"], "value": float(x["amount"])}
                for x in rows
            ],
            "method": "transaction attribution",
        }

    def _unpaid_balance(self, b, s, e, c):
        key = ("due", tuple(b.ids))
        if key not in c:
            jobs = self.env["laundry.job"].search(
                [
                    ("earlydryer_branch_id", "in", b.ids),
                    (
                        "state",
                        "not in",
                        ["collected", "delivered", "cancelled", "uncollected"],
                    ),
                    "|",
                    ("sale_order_id", "!=", False),
                    ("pos_order_id", "!=", False),
                ]
            )
            jobs.invalidate_recordset(
                ["amount_total", "amount_paid", "amount_due", "is_unpaid"]
            )
            by_branch = {branch.id: 0.0 for branch in b}
            for job in jobs:
                by_branch[job.earlydryer_branch_id.id] += job.amount_due
            c[key] = {
                "value": sum(by_branch.values()),
                "breakdown": [
                    {"branch_id": k, "value": v} for k, v in by_branch.items()
                ],
            }
        result = dict(c[key])
        today = fields.Date.context_today(self.with_context(tz="Africa/Lagos"))
        rows = self._query(
            c,
            ("aging", tuple(b.ids), today),
            SQL(
                """SELECT coalesce(sum(l.amount_residual),0) total,
   coalesce(sum(l.amount_residual) FILTER(WHERE %s-coalesce(l.date_maturity,l.date)<=30),0) current,
   coalesce(sum(l.amount_residual) FILTER(WHERE %s-coalesce(l.date_maturity,l.date) BETWEEN 31 AND 60),0) medium,
   coalesce(sum(l.amount_residual) FILTER(WHERE %s-coalesce(l.date_maturity,l.date)>60),0) old
   FROM account_move_line l JOIN account_account a ON a.id=l.account_id
   WHERE l.earlydryer_branch_id=ANY(%s) AND l.parent_state='posted' AND a.account_type='asset_receivable' AND l.amount_residual>0""",
                today,
                today,
                today,
                b.ids,
            ),
        )
        result["ageing"] = [
            {"label": label, "value": float(rows[0][key])}
            for key, label in [("current", "0–30"), ("medium", "31–60"), ("old", "60+")]
        ]
        result["receivables_total"] = float(rows[0]["total"])
        return result

    def _weights(self, b, s, e, c):
        start, end = utc_bounds(s, e)
        eligible = SQL(
            """SELECT i.id,coalesce(category.average_weight_kg,0) estimated_weight_kg
            FROM laundry_job_item i JOIN laundry_job j ON j.id=i.job_id
            LEFT JOIN earlydryer_garment_category category ON category.id=i.garment_category_id
            WHERE j.earlydryer_branch_id=ANY(%s) AND j.state!='cancelled' AND
            ((j.ready_on>=%s AND j.ready_on<%s) OR EXISTS(SELECT 1 FROM laundry_job_stage_log st WHERE st.job_id=j.id AND st.to_state='washed' AND st.date>=%s AND st.date<%s))""",
            b.ids,
            start,
            end,
            start,
            end,
        )
        if "earlydryer.wash.batch" in self.env:
            query = SQL(
                """WITH weighed AS(SELECT id,load_weight_kg FROM earlydryer_wash_batch WHERE earlydryer_branch_id=ANY(%s) AND state='done' AND batch_type='wash' AND finished_on>=%s AND finished_on<%s AND load_weight_kg>0),eligible AS(%s)
                SELECT (SELECT coalesce(sum(load_weight_kg),0) FROM weighed) weighed,
                coalesce(sum(estimated_weight_kg) FILTER(WHERE NOT EXISTS(SELECT 1 FROM earlydryer_wash_batch_item_rel rel JOIN weighed w ON w.id=rel.batch_id WHERE rel.item_id=eligible.id)),0) estimated FROM eligible""",
                b.ids,
                start,
                end,
                eligible,
            )
        else:
            query = SQL(
                "SELECT 0 weighed,coalesce(sum(estimated_weight_kg),0) estimated FROM (%s) eligible",
                eligible,
            )
        return self._query(c, ("weights", tuple(b.ids), s, e), query)[0]

    def _cost_per_kg(self, b, s, e, c):
        amounts = self._financial(b, s, e, c)
        excluded = set(b.company_id.earlydryer_retail_cogs_account_id.ids)
        consumables = set(b.company_id.earlydryer_consumables_account_id.ids)
        cost = sum(
            float(x["balance"])
            for x in amounts
            if x["account_id"] not in excluded
            and (
                x["account_type"] == "expense_direct_cost"
                or x["account_id"] in consumables
            )
        )
        weights = self._weights(b, s, e, c)
        weighed, estimated = float(weights["weighed"]), float(weights["estimated"])
        kg = weighed + estimated
        return {
            "value": cost / kg if kg else 0,
            "method": "mixed"
            if weighed and estimated
            else "weighed"
            if weighed
            else "estimated",
            "kg": kg,
            "direct_cost": cost,
            "weighed_kg": weighed,
            "estimated_kg": estimated,
        }

    def _rework_rate(self, b, s, e, c):
        start, end = utc_bounds(s, e)
        historical = (
            SQL(
                "SELECT r.item_id,'failed' result,r.date FROM laundry_job_item_rework r WHERE NOT EXISTS(SELECT 1 FROM earlydryer_report_qc_event e WHERE e.item_id=r.item_id AND e.result='failed' AND abs(extract(epoch FROM(e.date-r.date)))<5) UNION ALL"
            )
            if "laundry.job.item.rework" in self.env
            else SQL("")
        )
        rows = self._query(
            c,
            ("qc", tuple(b.ids), s, e),
            SQL(
                """WITH events AS(%s SELECT item_id,result,date FROM earlydryer_report_qc_event UNION ALL
   SELECT id,qc_state,qc_date FROM laundry_job_item i WHERE qc_state='passed' AND NOT EXISTS(SELECT 1 FROM earlydryer_report_qc_event e WHERE e.item_id=i.id AND e.result='passed'))
   SELECT count(DISTINCT events.item_id) FILTER(WHERE result='failed') failed,count(DISTINCT events.item_id) FILTER(WHERE result='passed') passed
   FROM events JOIN laundry_job_item i ON i.id=events.item_id WHERE i.earlydryer_branch_id=ANY(%s) AND events.date>=%s AND events.date<%s""",
                historical,
                b.ids,
                start,
                end,
            ),
        )[0]
        return {
            "value": rows["failed"] / rows["passed"] * 100 if rows["passed"] else 0,
            "failed_items": rows["failed"],
            "passed_items": rows["passed"],
            "method": "recorded QC history",
        }

    def _missing_items(self, b, s, e, c):
        start, end = utc_bounds(s, e)
        rows = self._query(
            c,
            ("missing", tuple(b.ids), s, e),
            SQL(
                "SELECT earlydryer_branch_id,count(DISTINCT item_id) amount FROM earlydryer_report_qc_event WHERE earlydryer_branch_id=ANY(%s) AND result='missing' AND date>=%s AND date<%s GROUP BY GROUPING SETS ((earlydryer_branch_id),())",
                b.ids,
                start,
                end,
            ),
        )
        return self._value(rows, "amount", b)

    def _productivity(self, b, s, e, c):
        start, end = utc_bounds(s, e)
        rows = self._query(
            c,
            ("productivity", tuple(b.ids), s, e),
            SQL(
                """SELECT s.employee_id,e.name employee,s.earlydryer_branch_id,s.from_state stage,count(*) moves,sum(items_moved) items,avg(hours_in_stage) hours
   FROM earlydryer_report_stage s LEFT JOIN hr_employee e ON e.id=s.employee_id
   WHERE s.earlydryer_branch_id=ANY(%s) AND s.date>=%s AND s.date<%s AND s.from_state IN ('sorted','washed','dried','ironed','qc','packed')
   GROUP BY s.employee_id,e.name,s.earlydryer_branch_id,s.from_state ORDER BY sum(items_moved) DESC""",
                b.ids,
                start,
                end,
            ),
        )
        return {
            "value": sum(x["items"] or 0 for x in rows),
            "rows": [dict(x, hours=float(x["hours"] or 0)) for x in rows],
            "moves_without_employee": sum(
                x["moves"] for x in rows if not x["employee_id"]
            ),
        }

    def _drill(self, code, b, s, e, c):
        model = REGISTRY[code][3]
        model = (
            "earlydryer.report." + model
            if model in ("job", "item", "stage", "sales", "discount")
            else model
        )
        domain = [("earlydryer_branch_id", "in", b.ids)]
        period = REGISTRY[code][4]
        start, end = utc_bounds(s, e)
        if period in ("period", "ready") and model in (
            "earlydryer.report.job",
            "earlydryer.report.item",
            "earlydryer.report.sales",
            "earlydryer.report.discount",
        ):
            field = (
                "ready_date"
                if period == "ready"
                else "date"
                if model.endswith(("sales", "discount"))
                else "received_date"
            )
            domain += [(field, ">=", str(s)), (field, "<=", str(e))]
        if period in ("stage", "wallet", "qc"):
            domain += [("date", ">=", str(start)), ("date", "<", str(end))]
        if period == "account":
            model = "earlydryer.report.ledger"
            domain = [
                ("earlydryer_branch_id", "in", b.ids),
                ("date", ">=", str(s)),
                ("date", "<=", str(e)),
                (
                    "account_type",
                    "in",
                    ["income", "income_other"]
                    if code == "revenue_posted"
                    else ["expense", "expense_direct_cost", "expense_depreciation"],
                ),
            ]
        if code == "overdue_count":
            domain += [("is_overdue", "=", True)]
        if code == "ready_uncollected_count":
            domain += [("state", "=", "ready")]
        if code == "retail_sales":
            domain += [("product_kind", "=", "retail")]
        if code == "missing_items":
            rows = self._query(
                c,
                ("drill-missing", tuple(b.ids), s, e),
                SQL(
                    "SELECT DISTINCT item_id id FROM earlydryer_report_qc_event WHERE earlydryer_branch_id=ANY(%s) AND result='missing' AND date>=%s AND date<%s",
                    b.ids,
                    start,
                    end,
                ),
            )
            domain = [("id", "in", [row["id"] for row in rows])]
        states = {
            "collected_count": "collected",
            "delivered_count": "delivered",
            "uncollected_count": "uncollected",
        }
        if code in states or code == "unpaid_releases":
            predicate = (
                SQL(
                    "earlydryer_release_unpaid AND to_state IN ('collected','delivered','out_for_delivery')"
                )
                if code == "unpaid_releases"
                else SQL("to_state=%s", states[code])
            )
            rows = self._query(
                c,
                ("drill-stage", code, tuple(b.ids), s, e),
                SQL(
                    "SELECT DISTINCT job_id id FROM earlydryer_report_stage WHERE earlydryer_branch_id=ANY(%s) AND date>=%s AND date<%s AND %s",
                    b.ids,
                    start,
                    end,
                    predicate,
                ),
            )
            model = "earlydryer.report.job"
            domain = [("id", "in", [row["id"] for row in rows])]
        if code in ("new_customers", "repeat_customers", "repeat_rate"):
            total = next(
                (
                    row
                    for row in self._jobs(b, s, e, c)
                    if row["earlydryer_branch_id"] is None
                ),
                {},
            )
            key = {
                "new_customers": "new_partner_ids",
                "repeat_customers": "repeat_partner_ids",
                "repeat_rate": "repeat_job_ids",
            }[code]
            if code != "repeat_rate":
                model = "res.partner"
            domain = [("id", "in", total.get(key) or [])]
        if code == "wallet_topups":
            domain += [("type", "=", "topup"), ("state", "=", "posted")]
        if code == "wallet_balance":
            domain += [("state", "=", "posted")]
        if code == "unpaid_balance":
            domain += [
                (
                    "state",
                    "not in",
                    ["collected", "delivered", "cancelled", "uncollected"],
                )
            ]
        return {"model": model, "domain": domain, "context": {}}

    def _legacy_eod_figures(self, branch, date):
        scope(self.env, branch.ids)
        self = branch  # noqa: PLW0642 -- Preserve the legacy EOD calculation verbatim.
        self.check_access("read")
        day = fields.Date.to_date(date)
        start = (
            datetime.combine(day, time.min, tzinfo=LAGOS)
            .astimezone(ZoneInfo("UTC"))
            .replace(tzinfo=None)
        )
        end = start + timedelta(days=1)
        jobs = self.env["laundry.job"].search([("earlydryer_branch_id", "=", self.id)])
        received = jobs.filtered(
            lambda j: start <= j.received_on < end and j.state != "cancelled"
        )
        completed = jobs.filtered(
            lambda j: (
                j.closed_on
                and start <= j.closed_on < end
                and j.state in ("collected", "delivered")
            )
        )
        orders = self.env["pos.order"].search(
            [
                ("config_id.earlydryer_branch_id", "=", self.id),
                ("date_order", ">=", start),
                ("date_order", "<", end),
                ("state", "in", ["paid", "done", "invoiced"]),
            ]
        )
        payments = {}
        for payment in orders.payment_ids:
            key = payment.payment_method_id.name
            payments[key] = payments.get(key, 0) + payment.amount
        backend_payments = self.env["account.payment"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("date", "=", day),
                ("payment_type", "=", "inbound"),
                ("move_id.state", "=", "posted"),
                ("state", "in", ["in_process", "paid"]),
            ]
        )
        backend_payments = backend_payments.filtered(
            lambda payment: (
                self.env["earlydryer.notify.message"]._branch(payment) == self
            )
        )
        for payment in backend_payments:
            key = payment.journal_id.name
            payments[key] = payments.get(key, 0) + payment.amount
        topups = self.env["earlydryer.wallet.transaction"].search(
            [
                ("earlydryer_branch_id", "=", self.id),
                ("state", "=", "posted"),
                ("type", "=", "topup"),
                ("date", ">=", start),
                ("date", "<", end),
            ]
        )
        scans = self.env["earlydryer.scan.log"].search_count(
            [
                ("earlydryer_branch_id", "=", self.id),
                ("is_mismatch", "=", True),
                ("date", ">=", start),
                ("date", "<", end),
            ]
        )
        return {
            "orders": len(received),
            "sales_value": sum(received.mapped("amount_total")),
            "collected": len(completed.filtered(lambda j: j.state == "collected")),
            "delivered": len(completed.filtered(lambda j: j.state == "delivered")),
            "ready": len(jobs.filtered(lambda j: j.state == "ready")),
            "overdue": len(jobs.filtered("is_overdue")),
            "payments": payments,
            "cash": sum(
                payment.amount
                for payment in backend_payments
                if payment.journal_id.type == "cash"
            )
            + sum(
                p.amount
                for p in orders.payment_ids
                if p.payment_method_id.is_cash_count
            ),
            "discounts": sum(
                line.qty * line.price_unit * line.discount / 100
                for line in orders.lines
            ),
            "unpaid_releases": len(completed.filtered("earlydryer_released_unpaid")),
            "wallet_topups": sum(topups.mapped("amount")),
            "scan_mismatches": scans,
        }

    def _dashboard_meta(self, b, s, e, c, staff_only=False):
        result = {
            "branches": [{"id": branch.id, "name": branch.name} for branch in b],
            "locked": not self.env.user._earlydryer_has_all_branches(),
            "staff": has_any(self.env, STAFF_GROUPS),
            "empty": False,
        }
        if staff_only:
            return result
        daily = self._query(
            c,
            ("daily", tuple(b.ids), s, e),
            SQL(
                "SELECT earlydryer_branch_id,received_date date,sum(amount_total) value FROM earlydryer_report_job WHERE earlydryer_branch_id=ANY(%s) AND received_date BETWEEN %s AND %s GROUP BY earlydryer_branch_id,received_date ORDER BY received_date",
                b.ids,
                s,
                e,
            ),
        )
        services = self._turnaround_services(b, s, e, c)
        start, end = utc_bounds(s, e)
        top = self._query(
            c,
            ("top_services", tuple(b.ids), s, e),
            SQL(
                "SELECT i.service_type_id,t.name name,sum(i.price_unit) value FROM laundry_job_item i JOIN laundry_job j ON j.id=i.job_id JOIN earlydryer_service_type t ON t.id=i.service_type_id WHERE j.earlydryer_branch_id=ANY(%s) AND j.state!='cancelled' AND j.received_on>=%s AND j.received_on<%s GROUP BY i.service_type_id,t.name ORDER BY sum(i.price_unit) DESC LIMIT 5",
                b.ids,
                start,
                end,
            ),
        )
        result.update(
            daily=[
                dict(
                    row,
                    date=str(row["date"]),
                    value=float(row["value"]),
                    branch_name=b.browse(row["earlydryer_branch_id"]).name,
                )
                for row in daily
            ],
            services=[
                dict(
                    row,
                    name=(
                        row["name"].get(self.env.lang)
                        or row["name"].get("en_US")
                        or next(iter(row["name"].values()), "")
                    )
                    if isinstance(row["name"], dict)
                    else row["name"],
                    hours=float(row["hours"] or 0),
                    on_time=float(row["on_time"] or 0),
                )
                for row in services
            ],
            top_services=[
                dict(
                    row,
                    name=(
                        row["name"].get(self.env.lang)
                        or row["name"].get("en_US")
                        or next(iter(row["name"].values()), "")
                    )
                    if isinstance(row["name"], dict)
                    else row["name"],
                    value=float(row["value"]),
                )
                for row in top
            ],
            empty=not bool(daily),
        )
        return result

    def _turnaround_services(self, b, s, e, c):
        start, end = utc_bounds(s, e)
        rows = self._query(
            c,
            ("services", tuple(b.ids), s, e),
            SQL(
                """WITH per_service AS(
            SELECT DISTINCT j.id job_id,i.service_type_id,j.express,
            greatest(extract(epoch FROM(j.ready_on-j.received_on))/3600,0) turnaround_hours,
            (j.promised_on IS NOT NULL AND j.ready_on<=j.promised_on) on_time
            FROM laundry_job j JOIN laundry_job_item i ON i.job_id=j.id
            WHERE j.earlydryer_branch_id=ANY(%s) AND j.state!='cancelled' AND j.ready_on>=%s AND j.ready_on<%s)
            SELECT s.service_type_id,t.name name,s.express,avg(s.turnaround_hours) hours,percentile_cont(0.9) WITHIN GROUP(ORDER BY s.turnaround_hours) p90,avg(s.on_time::int)*100 on_time
            FROM per_service s JOIN earlydryer_service_type t ON t.id=s.service_type_id GROUP BY s.service_type_id,t.name,s.express""",
                b.ids,
                start,
                end,
            ),
        )
        return [
            dict(
                row,
                name=(
                    row["name"].get(self.env.lang)
                    or row["name"].get("en_US")
                    or next(iter(row["name"].values()), "")
                )
                if isinstance(row["name"], dict)
                else row["name"],
                hours=float(row["hours"] or 0),
                p90=float(row["p90"] or 0),
                on_time=float(row["on_time"] or 0),
            )
            for row in rows
        ]

    def _eod_figures(self, branch, date):
        result = self._legacy_eod_figures(branch, date)
        codes = [
            "orders_count",
            "orders_value",
            "ready_uncollected_count",
            "overdue_count",
            "wallet_topups",
        ]
        kpis = self.compute(codes, branch.ids, date, date)
        for key, code in [
            ("orders", "orders_count"),
            ("sales_value", "orders_value"),
            ("ready", "ready_uncollected_count"),
            ("overdue", "overdue_count"),
            ("wallet_topups", "wallet_topups"),
        ]:
            result[key] = (
                int(kpis[code]["value"])
                if key in ("orders", "ready", "overdue")
                else kpis[code]["value"]
            )
        return result
