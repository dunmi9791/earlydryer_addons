# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestTrips(LogisticsCommon):
    def test_bag_scan_moves_job(self):
        job_1, job_2 = self._sale_job(), self._sale_job()
        stop_1 = self._book("delivery", job_1)
        stop_2 = self._book("delivery", job_2)
        trip = self._trip(stop_1 | stop_2)
        result = self._load(trip, job_1)
        self.assertEqual(result["result"], "ok")
        self.assertEqual(job_1.state, "out_for_delivery")
        log = self.Log.search([("job_id", "=", job_1.id)], limit=1)
        self.assertEqual(log.to_state, "out_for_delivery")
        self.assertEqual(log.employee_id, self.emp_rider)
        self.assertEqual(stop_1.state, "en_route")
        self.assertTrue(self._messages("job_out_for_delivery", job_1))
        # not scanned: stays assigned and flagged
        self.assertEqual(job_2.state, "ready")
        self.assertEqual(stop_2.state, "assigned")
        self.assertTrue(stop_2.not_loaded)
        self.assertEqual(trip.not_loaded_count, 1)
        self.assertEqual(self._load(trip, job_1)["result"], "duplicate")
        other = self._sale_job()
        self.assertEqual(self._load(trip, other)["result"], "not_on_trip")

    def _failed_stop(self, reason=None):
        job = self._sale_job()
        stop = self._book("delivery", job)
        trip = self._trip(stop)
        self._load(trip, job)
        api = self.Api.with_user(self.user_rider)
        api.rider_arrive(self._uuid(), stop.id)
        api.rider_fail(
            self._uuid(), stop.id, (reason or self.reason_absent).id, "No answer"
        )
        return job, stop, trip

    def test_failed_delivery_and_reschedule(self):
        job, stop, _trip = self._failed_stop()
        self.assertEqual(stop.state, "failed")
        self.assertEqual(stop.fail_reason_id, self.reason_absent)
        self.assertEqual(job.state, "ready")
        self.assertTrue(self._messages("delivery_failed", stop))
        self.assertTrue(
            self._alerts("earlydryer_logistics.rule_alert_failed_delivery", stop)
        )
        action = stop.with_user(self.user_front_desk).action_reschedule()
        retry = self.Stop.browse(action["res_id"])
        self.assertEqual(retry.attempt, 2)
        self.assertEqual(retry.previous_stop_id, stop)
        self.assertEqual(stop.next_stop_id, retry)
        self.assertEqual(retry.state, "draft")
        # off by default; the delivery fee was charged with the first attempt
        self.assertEqual(retry.failed_fee_amount, 0.0)
        self.assertEqual(retry.fee_amount, 0.0)
        self.assertFalse(stop.failed_fee_applied)

    def test_failed_fee_when_configured(self):
        self.branch_1.write(
            {"earlydryer_failed_fee_mode": "flat", "earlydryer_failed_fee_amount": 700}
        )
        job, stop, _trip = self._failed_stop()
        due = job.amount_due
        retry = self.Stop.browse(stop.action_reschedule()["res_id"])
        self.assertEqual(retry.failed_fee_amount, 700)
        self.assertTrue(stop.failed_fee_applied)
        retry._earlydryer_set_slot(self._first_slot_key())
        retry.with_user(self.user_front_desk).action_schedule()
        self.assertTrue(retry.fee_charged)
        job.invalidate_recordset()
        self.assertAlmostEqual(job.amount_due, due + 700)
        failed_product = self.env.ref(
            "earlydryer_logistics.product_failed_delivery_fee"
        )
        self.assertIn(failed_product, job.sale_order_id.order_line.product_id)

    def test_no_failed_fee_for_reasons_without_fee(self):
        self.branch_1.write(
            {"earlydryer_failed_fee_mode": "flat", "earlydryer_failed_fee_amount": 700}
        )
        refused = self.env.ref("earlydryer_logistics.fail_reason_customer_reschedule")
        _job, stop, _trip = self._failed_stop(refused)
        retry = self.Stop.browse(stop.action_reschedule()["res_id"])
        self.assertEqual(retry.failed_fee_amount, 0.0)

    def _delivered_trip(self, vehicle=None):
        job = self._sale_job()
        stop = self._book("delivery", job)
        trip = self._trip(stop, vehicle_id=vehicle.id if vehicle else False)
        self._load(trip, job)
        api = self.Api.with_user(self.user_rider)
        api.rider_arrive(self._uuid(), stop.id)
        api.rider_complete(
            self._uuid(),
            stop.id,
            {"collection_method": "cash", "cash_collected": stop.cod_amount},
        )
        return trip, stop

    def _vehicle(self):
        brand = self.env["fleet.vehicle.model.brand"].create({"name": "T Brand"})
        model = self.env["fleet.vehicle.model"].create(
            {"name": "T Bike", "brand_id": brand.id}
        )
        return self.env["fleet.vehicle"].create(
            {"model_id": model.id, "license_plate": "T-1"}
        )

    def test_close_requires_resolved_stops(self):
        job = self._sale_job()
        stop = self._book("delivery", job)
        trip = self._trip(stop)
        with self.assertRaises(UserError):
            trip.with_user(self.user_manager)._earlydryer_close(0.0)
        with self.assertRaises(AccessError):
            trip.with_user(self.user_front_desk)._earlydryer_close(0.0)

    def test_close_with_shortage_handover_and_odometer(self):
        vehicle = self._vehicle()
        trip, stop = self._delivered_trip(vehicle)
        expected = stop.cash_collected
        self.assertAlmostEqual(trip.cash_expected, expected)
        trip.with_user(self.user_manager)._earlydryer_close(
            expected - 100, odometer_end=120
        )
        self.assertEqual(trip.state, "done")
        self.assertAlmostEqual(trip.cash_difference, -100)
        handover = trip.handover_move_id
        self.assertEqual(handover.state, "posted")
        self.assertEqual(handover.earlydryer_kind, "rider_handover")
        rider_account = self.branch_1.earlydryer_rider_account_id
        self.assertAlmostEqual(
            -sum(
                handover.line_ids.filtered(
                    lambda line: line.account_id == rider_account
                ).mapped("balance")
            ),
            expected - 100,
        )
        difference = trip.difference_move_id
        self.assertEqual(difference.state, "posted")
        short_line = difference.line_ids.filtered(lambda line: line.debit)
        self.assertAlmostEqual(short_line.debit, 100)
        self.assertEqual(short_line.account_id.account_type, "asset_receivable")
        self.assertEqual(short_line.partner_id, self.user_rider.partner_id)
        # the rider cash account is cleared
        self.assertAlmostEqual(
            sum(
                self.env["account.move.line"]
                .search(
                    [
                        ("account_id", "=", rider_account.id),
                        ("parent_state", "=", "posted"),
                        (
                            "move_id",
                            "in",
                            (handover | difference | stop.cod_payment_id.move_id).ids,
                        ),
                    ]
                )
                .mapped("balance")
            ),
            0.0,
        )
        self.assertTrue(
            self._alerts("earlydryer_logistics.rule_alert_rider_cash_short", trip)
        )
        self.assertEqual(trip.odometer_id.value, 120)
        self.assertEqual(trip.odometer_id.vehicle_id, vehicle)

    def test_close_shortage_to_cash_short_account(self):
        self.env.company.earlydryer_rider_short_mode = "cash_short"
        trip, stop = self._delivered_trip()
        trip.with_user(self.user_manager)._earlydryer_close(stop.cash_collected - 50)
        short_line = trip.difference_move_id.line_ids.filtered(lambda line: line.debit)
        self.assertEqual(
            short_line.account_id, self.env.company.earlydryer_cash_diff_account_id
        )

    def test_carrier_bill(self):
        expense = self.env["account.account"].create(
            {"name": "T 3PL", "code": "T6299", "account_type": "expense"}
        )
        self.env.company.earlydryer_carrier_expense_account_id = expense
        carrier = self.env["res.partner"].create(
            {"name": "T Carrier", "earlydryer_is_carrier": True}
        )
        job = self._sale_job(paid=True)
        stop = self._book("delivery", job)
        trip = self._trip(
            stop, carrier=carrier, carrier_fee=3000, carrier_reference="X1"
        )
        # a 3PL takes the deliveries at once
        self.assertEqual(job.state, "out_for_delivery")
        trip.with_user(self.user_manager).action_create_carrier_bill()
        bill = trip.carrier_bill_id
        self.assertEqual(bill.move_type, "in_invoice")
        self.assertEqual(bill.state, "draft")
        self.assertEqual(bill.partner_id, carrier)
        line = bill.invoice_line_ids
        self.assertEqual(line.account_id, expense)
        self.assertEqual(line.price_unit, 3000)
        analytic = self.branch_1.analytic_account_id
        if analytic:
            self.assertIn(str(analytic.id), line.analytic_distribution)
        with self.assertRaises(UserError):
            self.Api.with_user(self.user_rider).rider_arrive(self._uuid(), stop.id)

    def test_front_desk_cannot_plan(self):
        with self.assertRaises(AccessError):
            self.Trip.with_user(self.user_front_desk).create(
                {"earlydryer_branch_id": self.branch_1.id}
            )
