# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import datetime, timedelta

from odoo import fields
from odoo.addons.earlydryer_notifications.models.earlydryer_branch import (
    EarlydryerBranch as LegacyBranch,
)
from odoo.exceptions import AccessError
from odoo.tests import tagged

from ..tools import dates, utc_bounds
from .common import ReportingCommon


@tagged("post_install", "-at_install")
class TestKpi(ReportingCommon):
    def test_empty_dashboard(self):
        data = self.compute()
        self.assertTrue(data["_meta"]["empty"])
        self.assertTrue(
            all(
                value["value"] == 0
                for key, value in data.items()
                if not key.startswith("_")
            )
        )

    def test_orders_items_average_and_drill(self):
        first = self.job(100)
        second = self.job(200)
        data = self.compute(
            ["orders_count", "orders_value", "avg_order_value", "items_count"]
        )
        self.assertEqual(data["orders_count"]["value"], 2)
        self.assertEqual(data["orders_value"]["value"], 300)
        self.assertEqual(data["avg_order_value"]["value"], 150)
        self.assertEqual(data["items_count"]["value"], 2)
        drill = data["orders_count"]["drill"]
        rows = self.env[drill["model"]].search(drill["domain"])
        self.assertEqual(set(rows.job_id.ids), set((first | second).ids))

    def test_turnaround_percentile_and_ontime(self):
        self.job(hours=10)
        self.job(hours=30)
        data = self.compute(["turnaround_avg_h", "turnaround_p90_h", "on_time_pct"])
        self.assertEqual(data["turnaround_avg_h"]["value"], 20)
        self.assertEqual(data["turnaround_p90_h"]["value"], 28)
        self.assertEqual(data["on_time_pct"]["value"], 50)

    def test_lagos_boundaries(self):
        self.job(received=datetime(2026, 10, 1, 22, 30))  # 23:30 Lagos, Oct 1.
        self.job(received=datetime(2026, 10, 1, 23, 30))  # 00:30 Lagos, Oct 2.
        data = self.compute(["orders_count"], start="2026-10-01", end="2026-10-01")
        self.assertEqual(data["orders_count"]["value"], 1)
        self.assertEqual(
            utc_bounds(self.start, self.start)[0], datetime(2026, 9, 30, 23)
        )

    def test_previous_and_year_comparisons(self):
        self.job(200)
        self.job(100, received=datetime(2026, 9, 28, 9))
        self.job(50, received=datetime(2025, 10, 5, 9))
        previous = self.compute(["orders_value"])["orders_value"]
        year = self.compute(["orders_value"], compare="year")["orders_value"]
        self.assertEqual(previous["compare_value"], 100)
        self.assertEqual(previous["delta_pct"], 100)
        self.assertEqual(year["compare_value"], 50)
        self.assertEqual(year["delta_pct"], 300)
        self.assertEqual(
            dates("2024-02-29", "2024-02-29", "year")[2][0],
            fields.Date.to_date("2023-02-28"),
        )

    def test_overdue_now_ignores_period(self):
        self.job(received=fields.Datetime.now() - timedelta(days=2), promised=1)
        data = self.compute(["overdue_count"], start="2020-01-01", end="2020-01-01")[
            "overdue_count"
        ]
        self.assertEqual(data["value"], 1)
        self.assertTrue(data["point_in_time"])

    def test_ready_uncollected_now(self):
        self.job(hours=10)
        self.assertEqual(
            self.compute(["ready_uncollected_count"])["ready_uncollected_count"][
                "value"
            ],
            1,
        )

    def test_stage_completions_distinct_and_drill(self):
        job = self.job()
        for hours in (1, 2):
            self.env["laundry.job.stage.log"].create(
                {
                    "job_id": job.id,
                    "from_state": "ready",
                    "to_state": "collected",
                    "date": self.stamp + timedelta(hours=hours),
                }
            )
        result = self.compute(["collected_count"])["collected_count"]
        self.assertEqual(result["value"], 1)
        self.assertEqual(
            len(self.env[result["drill"]["model"]].search(result["drill"]["domain"])), 1
        )

    def test_unpaid_releases(self):
        job = self.job(500)
        self.env["laundry.job.stage.log"].create(
            {
                "job_id": job.id,
                "from_state": "ready",
                "to_state": "collected",
                "date": self.stamp,
            }
        )
        self.assertEqual(
            self.compute(["unpaid_releases"])["unpaid_releases"]["value"], 1
        )

    def test_new_repeat_and_rate(self):
        self.job(100, received=datetime(2026, 9, 20, 9))
        self.job(200)
        customer = self.env["res.partner"].create(
            {"name": "New reporting customer", "phone": "+2348035555555"}
        )
        self.job(300, partner=customer)
        data = self.compute(["new_customers", "repeat_customers", "repeat_rate"])
        self.assertEqual(data["new_customers"]["value"], 1)
        self.assertEqual(data["repeat_customers"]["value"], 1)
        self.assertEqual(data["repeat_rate"]["value"], 50)

    def test_financial_analytic_proration_and_drill(self):
        self.entry(
            200,
            account=self.income_account,
            distribution={
                str(self.branch_1.analytic_account_id.id): 50,
                str(self.branch_2.analytic_account_id.id): 50,
            },
        )
        self.entry(40)
        self.entry(80, branch=self.branch_2)
        data = self.compute(["revenue_posted", "expenses"])
        self.assertEqual(data["revenue_posted"]["value"], 100)
        self.assertEqual(data["expenses"]["value"], 40)
        drill = data["revenue_posted"]["drill"]
        self.assertEqual(
            sum(self.env[drill["model"]].search(drill["domain"]).mapped("amount")), 100
        )
        self.assertEqual(
            self.compute(["expenses"], branches=self.branch_1 | self.branch_2)[
                "expenses"
            ]["value"],
            120,
        )

    def test_unpaid_jobs_and_ageing(self):
        self.job(250)
        invoice = self._invoice(120, partner=self.customer)
        invoice.earlydryer_branch_id = self.branch_1
        invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        ).date_maturity = fields.Date.today() - timedelta(days=40)
        data = self.compute(["unpaid_balance"])["unpaid_balance"]
        self.assertEqual(data["value"], 250)
        self.assertEqual(data["ageing"][1]["value"], 120)

    def test_wallet_attribution(self):
        tx = self._topup(1000)
        data = self.compute(
            ["wallet_topups", "wallet_balance"],
            start=fields.Date.today(),
            end=fields.Date.today(),
        )
        self.assertEqual(data["wallet_topups"]["value"], tx.amount)
        self.assertEqual(data["wallet_balance"]["value"], 1000)
        self.assertEqual(
            self.compute(["wallet_balance"], branches=self.branch_2)["wallet_balance"][
                "value"
            ],
            0,
        )

    def test_discount_sale_and_pos(self):
        job = self.job(100)
        job.sale_order_id.order_line.discount = 10
        order = self._sync(
            self._wallet_payload([self._line(self.shirt_wi, 1, price=200, discount=5)])
        )
        order.date_order = self.stamp
        data = self.compute(["discount_value", "discount_pct"])
        self.assertEqual(data["discount_value"]["value"], 20)
        self.assertAlmostEqual(data["discount_pct"]["value"], 20 / 300 * 100, places=3)
        drill = data["discount_value"]["drill"]
        self.assertEqual(
            sum(self.env[drill["model"]].search(drill["domain"]).mapped("discount")), 20
        )

    def test_retail_sales_and_no_pos_invoice_double_count(self):
        retail = self.env["product.product"].create(
            {"name": "Reporting retail", "earlydryer_kind": "retail", "list_price": 100}
        )
        order = self._sync(self._wallet_payload([self._line(retail, 1, price=100)]))
        order.date_order = self.stamp
        result = self.compute(["retail_sales"])["retail_sales"]
        self.assertEqual(result["value"], 100)

    def test_cost_estimated_and_retail_excluded(self):
        job = self.job(hours=10)
        job.item_ids.garment_category_id.average_weight_kg = 2
        self.entry(40)
        self.env.company.earlydryer_retail_cogs_account_id = self.expense_account
        self.assertEqual(self.compute(["cost_per_kg"])["cost_per_kg"]["value"], 0)
        self.env.company.earlydryer_retail_cogs_account_id = False
        result = self.compute(["cost_per_kg"])["cost_per_kg"]
        self.assertEqual(result["method"], "estimated")
        self.assertEqual(result["kg"], 2)
        self.assertEqual(result["value"], 20)

    def test_rework_rate_and_missing_dates(self):
        job = self.job(hours=10)
        item = job.item_ids
        item.write({"qc_state": "rework", "qc_date": self.stamp, "rework_count": 1})
        item.write({"qc_state": "passed", "qc_date": self.stamp + timedelta(hours=1)})
        item.write({"missing": True, "earlydryer_missing_on": self.stamp})
        result = self.compute(["rework_rate", "missing_items"])
        self.assertEqual(result["rework_rate"]["value"], 100)
        self.assertEqual(result["missing_items"]["value"], 1)

    def test_productivity_and_exception_filters(self):
        job = self.job()
        log = self.env["laundry.job.stage.log"].create(
            {
                "job_id": job.id,
                "from_state": "washed",
                "to_state": "dried",
                "date": self.stamp + timedelta(hours=2),
                "employee_id": self.employee.id,
                "item_ids": [(6, 0, job.item_ids.ids)],
            }
        )
        result = self.compute(["productivity"])["productivity"]
        self.assertEqual(result["value"], 1)
        self.assertEqual(result["rows"][0]["moves"], 1)
        self.assertEqual(result["rows"][0]["stage"], "washed")
        self.assertEqual(result["rows"][0]["hours"], 2)
        self.assertEqual(
            self.env["earlydryer.report.stage"].browse(log.id).items_moved, 1
        )

    def test_branch_manager_scope(self):
        self.job(100)
        self.job(900, branch=self.branch_2)
        result = self.compute(
            ["orders_value"],
            branches=self.branch_1 | self.branch_2,
            user=self.user_manager,
        )
        self.assertEqual(result["orders_value"]["value"], 100)
        rows = self.env["earlydryer.report.job"].with_user(self.user_manager).search([])
        self.assertEqual(rows.earlydryer_branch_id, self.branch_1)

    def test_finance_has_no_staff(self):
        result = self.compute(user=self.user_finance)
        self.assertNotIn("productivity", result)
        with self.assertRaises(AccessError):
            self.compute(["productivity"], user=self.user_finance)
        with self.assertRaises(AccessError):
            self.env["earlydryer.report.stage"].with_user(self.user_finance).search([])

    def test_hr_productivity_only(self):
        result = self.compute(user=self.hr_user)
        self.assertEqual(set(result) - {"_meta"}, {"productivity"})
        with self.assertRaises(AccessError):
            self.compute(["orders_value"], user=self.hr_user)

    def test_frontdesk_no_dashboard(self):
        with self.assertRaises(AccessError):
            self.compute(user=self.user_front_desk)

    def test_eod_backward_compatible(self):
        self.job(300, received=fields.Datetime.now())
        self._topup(1000)
        day = fields.Date.today()
        expected = LegacyBranch._earlydryer_eod_figures(self.branch_1, day)
        self.assertEqual(self.branch_1._earlydryer_eod_figures(day), expected)

    def test_productivity_xlsx(self):
        self.job()
        wizard = self.env["earlydryer.productivity.wizard"].create(
            {
                "branch_ids": [(6, 0, self.branch_1.ids)],
                "date_from": self.start,
                "date_to": self.end,
            }
        )
        data, ext = self.env["ir.actions.report"]._render_xlsx(
            "earlydryer_reporting.action_productivity_xlsx",
            wizard.ids,
            {
                "branch_ids": self.branch_1.ids,
                "date_from": str(self.start),
                "date_to": str(self.end),
            },
        )
        self.assertTrue(data.startswith(b"PK"))
        self.assertEqual(ext, "xlsx")

    def test_new_customer_first_job_at_other_plant(self):
        self.job(branch=self.branch_2, received=datetime(2026, 10, 2, 9))
        self.job(received=datetime(2026, 10, 5, 9))
        result = self.compute(["new_customers", "repeat_customers"])
        self.assertEqual(result["new_customers"]["value"], 1)
        self.assertEqual(result["repeat_customers"]["value"], 0)

    def test_missing_then_found_retains_history(self):
        job = self.job()
        job.item_ids.write({"missing": True, "earlydryer_missing_on": self.stamp})
        job.item_ids.write({"missing": False})
        self.assertEqual(self.compute(["missing_items"])["missing_items"]["value"], 1)

    def test_weighed_then_mixed_cost(self):
        if "earlydryer.wash.batch" not in self.env:
            self.skipTest("Optional Production is not installed in this profile")
        self.branch_1.use_wash_batches = True
        first = self.job(hours=10)
        first.item_ids.garment_category_id.average_weight_kg = 2
        self.entry(40)
        self.env["earlydryer.wash.batch"].create(
            {
                "earlydryer_branch_id": self.branch_1.id,
                "state": "done",
                "batch_type": "wash",
                "finished_on": self.stamp,
                "load_weight_kg": 4,
                "item_ids": [(6, 0, first.item_ids.ids)],
            }
        )
        weighed = self.compute(["cost_per_kg"])["cost_per_kg"]
        self.assertEqual(weighed["method"], "weighed")
        self.assertEqual(weighed["value"], 10)
        self.job(hours=10)
        mixed = self.compute(["cost_per_kg"])["cost_per_kg"]
        self.assertEqual(mixed["method"], "mixed")
        self.assertEqual(mixed["kg"], 6)
        self.assertAlmostEqual(mixed["value"], 40 / 6, places=3)

    def test_stage_source_when_production_present(self):
        if "source" not in self.env["laundry.job.stage.log"]._fields:
            self.skipTest("Optional Production is not installed in this profile")
        job = self.job()
        log = (
            self.env["laundry.job.stage.log"]
            .with_context(earlydryer_move_source="tablet")
            .create(
                {
                    "job_id": job.id,
                    "from_state": "washed",
                    "to_state": "dried",
                    "date": self.stamp + timedelta(hours=2),
                    "employee_id": self.employee.id,
                }
            )
        )
        self.assertEqual(
            self.env["earlydryer.report.stage"].browse(log.id).source, "tablet"
        )

    def test_productivity_exceptions(self):
        job = self.job()
        wrong = self.env["laundry.job.stage.log"].create(
            {
                "job_id": job.id,
                "from_state": "washed",
                "to_state": "dried",
                "date": self.stamp + timedelta(seconds=10),
                "employee_id": self.employee_2.id,
            }
        )
        row = self.env["earlydryer.report.stage"].browse(wrong.id)
        self.assertTrue(row.outside_plant)
        self.assertTrue(row.fast_move)
        self.assertIn(
            row, self.env["earlydryer.report.stage"].search([("fast_move", "=", True)])
        )
