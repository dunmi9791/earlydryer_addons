# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from .common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestPickupFlow(LogisticsCommon):
    def _done_pickup(self, **book_vals):
        stop = self._book("pickup", user=self.user_cs, **book_vals)
        self._trip(stop)
        api = self.Api.with_user(self.user_rider)
        api.rider_arrive(
            self._uuid(), stop.id, {"lat": 9.08, "lng": 7.47, "accuracy": 10}
        )
        api.rider_complete(
            self._uuid(),
            stop.id,
            {"recipient_name": "T", "bag_count": 2, "piece_count_estimate": 9},
        )
        return stop

    def test_pickup_needs_bag_count(self):
        stop = self._book("pickup", user=self.user_cs)
        self._trip(stop)
        with self.assertRaises(UserError):
            self.Api.with_user(self.user_rider).rider_complete(
                self._uuid(), stop.id, {"recipient_name": "T"}
            )

    def test_pickup_priced_in_backend(self):
        stop = self._done_pickup()
        self.assertTrue(self._messages("pickup_booked", stop))
        self.assertTrue(self._messages("pickup_done", stop))
        self.assertEqual(stop.state, "done")
        self.assertEqual(stop.bag_count, 2)
        arrived = self.Stop.with_user(self.user_front_desk).search(
            [
                ("stop_type", "=", "pickup"),
                ("state", "=", "done"),
                ("job_id", "=", False),
            ]
        )
        self.assertIn(stop, arrived)
        action = stop.with_user(self.user_front_desk).action_price_backend()
        order = self.env["sale.order"].browse(action["res_id"])
        self.assertEqual(order.earlydryer_pickup_stop_id, stop)
        self.assertEqual(order.earlydryer_channel, "pickup")
        self.assertTrue(stop.plant_arrival_on)
        order.order_line = [
            Command.create({"product_id": self.shirt_wi.id, "product_uom_qty": 3})
        ]
        order.action_confirm()
        job = order.laundry_job_ids
        self.assertEqual(stop.job_id, job)
        self.assertEqual(job.channel, "pickup")
        self.assertEqual(job.received_on, stop.plant_arrival_on)
        # the customer hears the count and the price now
        self.assertTrue(self._messages("job_received", job))

    def test_pickup_priced_in_pos(self):
        stop = self._done_pickup(return_delivery=True)
        stop._earlydryer_mark_at_plant()
        info = self.Stop.with_user(self.user_front_desk).earlydryer_pos_pickup_info(
            stop.id, self.config.id
        )
        self.assertTrue(info["ok"])
        self.assertEqual(info["partner_id"], self.partner.id)
        self.assertEqual(info["fulfilment"], "deliver")
        order = self._sync(
            self._payload(
                [self._line(self.shirt_wi, 2)],
                earlydryer_pickup_stop_id=stop.id,
                earlydryer_fulfilment="deliver",
            )
        )
        self.assertEqual(order.earlydryer_pickup_stop_id, stop)
        job = order.earlydryer_job_id
        self.assertTrue(job)
        self.assertEqual(stop.job_id, job)
        self.assertEqual(job.channel, "pickup")
        self.assertEqual(job.fulfilment, "deliver")
        self.assertEqual(job.received_on, stop.plant_arrival_on)

    def test_return_delivery_drafted_when_ready(self):
        stop = self._done_pickup(return_delivery=True)
        order = self.env["sale.order"].browse(stop.action_price_backend()["res_id"])
        order.order_line = [
            Command.create({"product_id": self.shirt_wi.id, "product_uom_qty": 1})
        ]
        order.action_confirm()
        job = order.laundry_job_ids
        self.assertEqual(job.fulfilment, "deliver")
        self.branch_1.earlydryer_auto_draft_delivery = True
        self._make_ready(job)
        job._earlydryer_on_state_changed("packed", "ready")
        delivery = self.Stop.search(
            [("job_id", "=", job.id), ("stop_type", "=", "delivery")]
        )
        self.assertEqual(delivery.state, "draft")
        self.assertEqual(delivery.address_partner_id, stop.address_partner_id)
