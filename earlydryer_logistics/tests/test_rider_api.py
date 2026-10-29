# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import json

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import LogisticsCommon

# 1x1 transparent PNG
PIXEL = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
).decode()


@tagged("post_install", "-at_install")
class TestRiderApi(LogisticsCommon):
    def _pickup_trip(self, rider=None, partner=None):
        stop = self._book("pickup", user=self.user_cs, partner=partner)
        trip = self._trip(stop, rider=rider)
        return stop, trip

    def test_rider_data_is_json(self):
        stop, trip = self._pickup_trip()
        data = self.Api.with_user(self.user_rider).rider_data()
        json.dumps(data)
        self.assertEqual([t["id"] for t in data["trips"]], [trip.id])
        card = data["trips"][0]["stops"][0]
        self.assertEqual(card["id"], stop.id)
        self.assertTrue(card["tel_url"].startswith("tel:+234"))
        self.assertTrue(card["whatsapp_url"].startswith("https://wa.me/234"))
        self.assertIn("maps", card["map_url"])

    def test_idempotent_per_client_uuid(self):
        stop, _trip = self._pickup_trip()
        api = self.Api.with_user(self.user_rider)
        uuid = self._uuid()
        first = api.rider_arrive(
            uuid, stop.id, {"lat": 9.08, "lng": 7.47, "accuracy": 5}
        )
        second = api.rider_arrive(uuid, stop.id, {"lat": 1, "lng": 1, "accuracy": 5})
        self.assertFalse(first.get("duplicate"))
        self.assertTrue(second["duplicate"])
        self.assertAlmostEqual(stop.gps_lat, 9.08)
        self.assertEqual(
            self.env["earlydryer.logistics.client.action"].search_count(
                [("uuid", "=", uuid)]
            ),
            1,
        )
        photo_uuid = self._uuid()
        api.rider_upload_photo(photo_uuid, stop.id, PIXEL, "image/png")
        api.rider_upload_photo(photo_uuid, stop.id, PIXEL, "image/png")
        self.assertEqual(len(stop.photo_ids), 1)

    def test_rider_sees_only_own_trips(self):
        stop, trip = self._pickup_trip(rider=self.emp_rider_2)
        api = self.Api.with_user(self.user_rider)
        self.assertFalse(api.rider_data()["trips"])
        self.assertFalse(
            self.Stop.with_user(self.user_rider).search([("id", "=", stop.id)])
        )
        self.assertFalse(
            self.Trip.with_user(self.user_rider).search([("id", "=", trip.id)])
        )
        with self.assertRaises(AccessError):
            api.rider_arrive(self._uuid(), stop.id)
        self.assertTrue(
            self.Stop.with_user(self.user_rider_2).search([("id", "=", stop.id)])
        )

    def test_low_accuracy_flagged_not_refused(self):
        stop, _trip = self._pickup_trip()
        result = self.Api.with_user(self.user_rider).rider_arrive(
            self._uuid(), stop.id, {"lat": 9.08, "lng": 7.47, "accuracy": 250}
        )
        self.assertEqual(stop.state, "arrived")
        self.assertTrue(result["low_accuracy"])
        self.assertTrue(stop.gps_low_accuracy)

    def test_save_location_for_customer(self):
        customer = self.env["res.partner"].create(
            {
                "name": "T No GPS",
                "phone": "+2348030000999",
                "earlydryer_area_id": self.area_near.id,
            }
        )
        stop, _trip = self._pickup_trip(partner=customer)
        api = self.Api.with_user(self.user_rider)
        api.rider_arrive(self._uuid(), stop.id)
        api.rider_complete(
            self._uuid(),
            stop.id,
            {
                "bag_count": 1,
                "save_location": True,
                "gps": {"lat": 9.0811, "lng": 7.4699, "accuracy": 12},
                "office_approved": True,  # never accepted from the phone
            },
        )
        self.assertAlmostEqual(customer.partner_latitude, 9.0811)
        self.assertAlmostEqual(customer.earlydryer_gps_accuracy_m, 12)
