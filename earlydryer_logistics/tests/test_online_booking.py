# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestOnlineBooking(LogisticsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # anonymous website visitor: the service needs no rights
        cls.Booking = cls.env["earlydryer.logistics.booking"].with_user(
            cls.env.ref("base.public_user")
        )

    def _payload(self, **vals):
        slot_key = vals.pop("slot_key", None) or self._first_slot_key("pickup")
        return {
            "name": "T Online Customer",
            "phone": "0809 111 2233",
            "area_id": self.area_near.id,
            "street": "12 T Street",
            "landmark": "T green gate",
            "slot_key": slot_key,
            "source": "website",
            "notify_opt_in": True,
            **vals,
        }

    def _stop(self, result):
        return self.Stop.search([("name", "=", result["reference"])])

    def test_public_areas_lists_served_areas_only(self):
        ids = [area["id"] for area in self.Booking.public_areas()]
        self.assertIn(self.area_near.id, ids)
        self.assertIn(self.area_far.id, ids)
        self.assertNotIn(self.area_unserved.id, ids)

    def test_quote(self):
        quote = self.Booking.quote_pickup(
            {"area_id": self.area_near.id, "date": str(self.tomorrow), "days": 1}
        )
        self.assertTrue(quote["served"])
        self.assertEqual(quote["plant"], self.branch_1.name)
        self.assertTrue(quote["slots"])
        self.assertNotIn("template_id", quote["slots"][0])
        unserved = self.Booking.quote_pickup({"area_id": self.area_unserved.id})
        self.assertFalse(unserved["served"])
        self.assertFalse(unserved["slots"])

    def test_book_schedules_and_notifies(self):
        result = self.Booking.book_pickup(self._payload())
        stop = self._stop(result)
        self.assertEqual(stop.state, "scheduled")
        self.assertEqual(stop.source, "website")
        self.assertEqual(stop.stop_type, "pickup")
        self.assertEqual(stop.earlydryer_branch_id, self.branch_1)
        self.assertEqual(stop.zone_id, self.zone_flat)
        self.assertEqual(stop.area_id, self.area_near)
        self.assertEqual(stop.landmark, "T green gate")
        self.assertTrue(stop.slot_start)
        self.assertTrue(result["access_token"])
        self.assertEqual(result["state"], "scheduled")
        self.assertTrue(self._messages("pickup_booked", stop))
        self.assertTrue(
            self._alerts("earlydryer_logistics.rule_alert_pickup_online", stop)
        )
        self.assertEqual(stop.partner_id.phone, "+2348091112233")

    def test_no_customer_message_without_consent(self):
        result = self.Booking.book_pickup(self._payload(notify_opt_in=False))
        stop = self._stop(result)
        self.assertEqual(stop.state, "scheduled")
        self.assertFalse(stop.partner_id.earlydryer_notify_opt_in)
        self.assertFalse(self._messages("pickup_booked", stop))

    def test_fee_comes_from_the_quote(self):
        self.zone_flat.pickup_fee = 500
        result = self.Booking.book_pickup(self._payload(fee=0, fee_amount=0))
        self.assertEqual(result["fee"], 500)
        self.assertEqual(self._stop(result).fee_amount, 500)

    def test_existing_customer_matched_by_phone(self):
        # self.partner has "+234 800 555 0101"
        result = self.Booking.book_pickup(
            self._payload(name="", phone="08005550101", street="1 T Road")
        )
        stop = self._stop(result)
        self.assertEqual(stop.partner_id, self.partner)
        # self.partner has an area but no street: a delivery address is added
        self.assertEqual(stop.address_partner_id.parent_id, self.partner)
        self.assertEqual(stop.address_partner_id.type, "delivery")
        again = self.Booking.book_pickup(
            self._payload(
                name="", phone="+2348005550101", street="1 T Road", client_ref="x2"
            )
        )
        self.assertEqual(self._stop(again).address_partner_id, stop.address_partner_id)

    def test_unserved_and_invalid_refused(self):
        with self.assertRaises(UserError):
            self.Booking.book_pickup(self._payload(area_id=self.area_unserved.id))
        with self.assertRaises(UserError):
            self.Booking.book_pickup(self._payload(phone="12"))
        with self.assertRaises(UserError):
            self.Booking.book_pickup(self._payload(slot_key="nonsense"))
        with self.assertRaises(UserError):
            self.Booking.book_pickup(self._payload(source="backend"))

    def test_full_slot_refused(self):
        key = self._first_slot_key("pickup")
        template, _day = self.Slot._earlydryer_parse_key(key)
        template.capacity = 1
        self.Booking.book_pickup(self._payload(slot_key=key))
        with self.assertRaises(UserError):
            self.Booking.book_pickup(
                self._payload(slot_key=key, phone="0809 999 0000")
            )

    def test_client_ref_is_idempotent(self):
        first = self.Booking.book_pickup(self._payload(client_ref="abc-1"))
        second = self.Booking.book_pickup(self._payload(client_ref="abc-1"))
        self.assertEqual(first["reference"], second["reference"])
        self.assertEqual(
            self.Stop.search_count([("client_ref", "=", "abc-1")]), 1
        )

    def test_open_pickups_capped_per_phone(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "earlydryer_logistics.online_max_open_pickups", "2"
        )
        self.Booking.book_pickup(self._payload())
        self.Booking.book_pickup(self._payload())
        with self.assertRaises(UserError):
            self.Booking.book_pickup(self._payload())

    def test_track_and_cancel(self):
        result = self.Booking.book_pickup(self._payload())
        reference, token = result["reference"], result["access_token"]
        with self.assertRaises(UserError):
            self.Booking.get_pickup(reference, "wrong")
        self.assertTrue(self.Booking.get_pickup(reference, token)["cancellable"])
        cancelled = self.Booking.cancel_pickup(reference, token)
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(self._stop(result).state, "cancelled")

    def test_cancel_refused_after_cutoff_or_on_trip(self):
        result = self.Booking.book_pickup(self._payload())
        stop = self._stop(result)
        self._engine(stop).slot_start = fields.Datetime.now() + timedelta(minutes=30)
        with self.assertRaises(UserError):
            self.Booking.cancel_pickup(result["reference"], result["access_token"])
        other = self.Booking.book_pickup(self._payload())
        self._trip(self._stop(other), start=False)
        with self.assertRaises(UserError):
            self.Booking.cancel_pickup(other["reference"], other["access_token"])

    def test_backend_stops_cannot_be_cancelled_online(self):
        stop = self._book("pickup", user=self.user_cs)
        self.assertFalse(stop.sudo().access_token)
        with self.assertRaises(UserError):
            self.Booking.cancel_pickup(stop.name, "")

    def test_callback_request(self):
        # served area, but no time offered suits the customer
        result = self.Booking.request_callback(self._payload(note="Please call"))
        stop = self._stop(result)
        self.assertEqual(stop.state, "draft")
        self.assertFalse(stop.fee_amount)
        self.assertFalse(self._messages("pickup_booked", stop))
        self.assertTrue(stop.activity_ids)
        self.assertIn(self.user_cs, stop.activity_ids.user_id)
        unserved = self.Booking.request_callback(
            self._payload(area_id=self.area_unserved.id, phone="0809 555 0000")
        )
        self.assertEqual(self._stop(unserved).state, "draft")
