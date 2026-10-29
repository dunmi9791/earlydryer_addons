# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from ..models.earlydryer_kpi import LOGISTICS_KPIS
from .common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestKpiNotifications(LogisticsCommon):
    def test_delivery_scheduled_message_carries_fee(self):
        job = self._sale_job()
        stop = self._book("delivery", job)
        message = self._messages("delivery_scheduled", stop)
        self.assertEqual(len(message), 1)
        context = json.loads(message.render_context_json)
        self.assertIn("1,500.00", context["fee"])
        self.assertTrue(context["slot"])
        self.assertIn("1,500.00", message.body)

    def test_logistics_kpis(self):
        api = self.Api.with_user(self.user_rider)
        # one pickup done, one delivery done with cash, one delivery failed
        pickup = self._book("pickup", user=self.user_cs)
        job_ok, job_ko = self._sale_job(), self._sale_job()
        ok = self._book("delivery", job_ok)
        ko = self._book("delivery", job_ko)
        trip = self._trip(pickup | ok | ko)
        self._load(trip, job_ok)
        self._load(trip, job_ko)
        api.rider_arrive(self._uuid(), pickup.id)
        api.rider_complete(self._uuid(), pickup.id, {"bag_count": 1})
        api.rider_arrive(self._uuid(), ok.id)
        api.rider_complete(
            self._uuid(),
            ok.id,
            {"collection_method": "cash", "cash_collected": ok.cod_amount},
        )
        api.rider_fail(self._uuid(), ko.id, self.reason_absent.id)
        trip.with_user(self.user_manager)._earlydryer_close(trip.cash_expected - 10)
        today = fields.Date.context_today(self.Stop)
        Kpi = self.env["earlydryer.kpi"]
        codes = list(LOGISTICS_KPIS)
        # from yesterday: accounting dates are UTC dates, the period is a
        # Lagos date (a run just after midnight would miss the invoice)
        start = today - timedelta(days=1)
        kpis = Kpi.with_user(self.user_ops).compute(
            codes, self.branch_1.ids, start, self.tomorrow
        )
        value = {code: kpis[code]["value"] for code in codes}
        self.assertEqual(value["logistics_pickups_done"], 1)
        self.assertEqual(value["logistics_deliveries_done"], 1)
        self.assertAlmostEqual(value["logistics_failed_pct"], 33.33)
        self.assertEqual(
            kpis["logistics_failed_pct"]["top_reasons"],
            [{"name": self.reason_absent.name, "value": 1}],
        )
        self.assertAlmostEqual(value["logistics_cod_collected"], ok.cash_collected)
        self.assertAlmostEqual(value["logistics_cash_difference"], -10.0)
        self.assertAlmostEqual(value["logistics_stops_per_trip"], 3.0)
        # the fee of the delivered job was invoiced with its order at the door
        self.assertAlmostEqual(value["logistics_fee_revenue"], 1500)
        self.assertEqual(value["logistics_carrier_cost"], 0.0)
        self.assertEqual(value["logistics_on_slot_pct"], 0.0)
        self.assertEqual(
            kpis["logistics_deliveries_done"]["drill"]["model"],
            "earlydryer.logistics.stop",
        )
        drill = kpis["logistics_deliveries_done"]["drill"]
        self.assertEqual(self.Stop.search(drill["domain"]), ok)
        # the Logistics section is for Operations Managers and above
        with self.assertRaises(AccessError):
            Kpi.with_user(self.user_manager).compute(
                codes, self.branch_1.ids, today, self.tomorrow
            )
        dashboard = Kpi.with_user(self.user_manager).compute(
            [], self.branch_1.ids, today, self.tomorrow, dashboard=True
        )
        self.assertFalse(set(dashboard) & set(codes))
        dashboard = Kpi.with_user(self.user_ops).compute(
            [], self.branch_1.ids, today, self.tomorrow, dashboard=True
        )
        self.assertTrue(set(codes) <= set(dashboard))
