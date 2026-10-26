# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json
from datetime import datetime, time, timedelta

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import tagged

from .common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestQuoteSlots(LogisticsCommon):
    def _quote(self, partner=None, stop_type="delivery", express=False, amount=0.0):
        return self.Quote.quote(
            partner or self.partner,
            partner or self.partner,
            self.branch_1,
            stop_type,
            self.tomorrow,
            express=express,
            order_amount=amount,
        )

    def _customer(self, area, lat=0.0, lng=0.0):
        return self.env["res.partner"].create(
            {
                "name": f"T {area.name}",
                "earlydryer_area_id": area.id,
                "partner_latitude": lat,
                "partner_longitude": lng,
            }
        )

    def test_quote_flat_zone(self):
        quote = self._quote()
        self.assertTrue(quote["served"])
        self.assertEqual(quote["zone_id"], self.zone_flat.id)
        self.assertEqual(quote["fee"], 1500)
        self.assertTrue(quote["available_slots"])
        self.assertTrue(quote["distance_km"] > 0)
        # plain JSON-safe values (website API later)
        json.dumps(quote)

    def test_quote_distance_zone_and_max_km(self):
        customer = self._customer(self.area_far)  # no GPS: centre of the area
        straight = self.Quote._earlydryer_haversine_km((9.0790, 7.4700), (9.1550, 7.3220))
        distance = round(straight * 1.3, 2)
        quote = self._quote(customer)
        self.assertTrue(quote["served"])
        self.assertAlmostEqual(quote["distance_km"], distance, places=2)
        self.assertAlmostEqual(quote["fee"], round(1000 + 100 * distance, 2), places=2)
        self.assertEqual(len(quote["fee_breakdown"]), 2)
        self.zone_distance.max_km = 10
        quote = self._quote(customer)
        self.assertFalse(quote["served"])
        self.assertEqual(quote["fee"], 0.0)
        self.assertIn("beyond", quote["message"])

    def test_quote_express(self):
        self.assertEqual(self._quote(express=True)["fee"], 2500)

    def test_quote_free_over_and_minimum(self):
        customer = self._customer(self.area_mid)
        quote = self._quote(customer, amount=12000)
        self.assertEqual(quote["fee"], 0.0)
        self.assertFalse(quote["below_minimum"])
        # free over the threshold, the express fee still applies
        self.assertEqual(self._quote(customer, express=True, amount=12000)["fee"], 500)
        quote = self._quote(customer, amount=2000)
        self.assertEqual(quote["fee"], 2000)
        self.assertTrue(quote["below_minimum"])
        self.assertIn("minimum", quote["message"])

    def test_quote_unserved_area(self):
        quote = self._quote(self._customer(self.area_unserved))
        self.assertFalse(quote["served"])
        self.assertFalse(quote["zone_id"])
        self.assertIn("not served", quote["message"])
        no_area = self.env["res.partner"].create({"name": "T No area"})
        self.assertFalse(self._quote(no_area)["served"])

    def test_quote_pickup_fee(self):
        self.assertEqual(self._quote(stop_type="pickup")["fee"], 0.0)
        self.zone_flat.pickup_fee = 300
        self.assertEqual(self._quote(stop_type="pickup")["fee"], 300)

    def test_area_in_one_zone_per_plant(self):
        with self.assertRaises(ValidationError):
            self.zone_distance.area_ids = [Command.link(self.area_near.id)]
        # another plant may serve the same area
        self.Zone.create(
            {
                "name": "T Plant 2 zone",
                "earlydryer_branch_id": self.branch_2.id,
                "flat_fee": 100,
                "area_ids": [Command.set(self.area_near.ids)],
            }
        )

    def test_slots_capacity(self):
        slots = self.Slot.available_slots(
            self.branch_1, "pickup", self.tomorrow, self.tomorrow
        )
        self.assertEqual(len(slots), 2)
        morning = slots[0]
        template = self.Slot.browse(morning["template_id"])
        template.capacity = 1
        stop = self.Stop.create(
            {"stop_type": "pickup", "partner_id": self.partner.id,
             "earlydryer_branch_id": self.branch_1.id}
        )
        stop._earlydryer_set_slot(morning["key"])
        keys = [
            slot["key"]
            for slot in self.Slot.available_slots(
                self.branch_1, "pickup", self.tomorrow, self.tomorrow
            )
        ]
        self.assertNotIn(morning["key"], keys)
        full = self.Slot.available_slots(
            self.branch_1, "pickup", self.tomorrow, self.tomorrow, include_full=True
        )
        self.assertEqual(full[0]["remaining"], 0)

    def test_slots_cutoff_and_past(self):
        morning = self.Slot.search(
            [
                ("earlydryer_branch_id", "=", self.branch_1.id),
                ("weekday", "=", str(self.tomorrow.weekday())),
                ("name", "=", "Morning"),
            ]
        )
        start, _end = morning._earlydryer_bounds(self.tomorrow)
        # one hour before the start: inside the 2 h cut-off
        slots = self.Slot.available_slots(
            self.branch_1, "delivery", self.tomorrow, self.tomorrow,
            now=start - timedelta(hours=1),
        )
        self.assertEqual([slot["name"] for slot in slots], ["Afternoon"])
        # after the day: nothing
        self.assertFalse(
            self.Slot.available_slots(
                self.branch_1, "delivery", self.tomorrow, self.tomorrow,
                now=start + timedelta(days=1),
            )
        )

    def test_slots_skip_public_holidays(self):
        calendar = self.env["resource.calendar"].create({"name": "T Plant hours"})
        self.branch_1.resource_calendar_id = calendar
        day_start = datetime.combine(self.tomorrow, time(0)) - timedelta(hours=1)
        self.env["resource.calendar.leaves"].create(
            {
                "name": "T Public holiday",
                "calendar_id": calendar.id,
                "date_from": day_start,
                "date_to": day_start + timedelta(hours=24),
            }
        )
        self.assertFalse(
            self.Slot.available_slots(
                self.branch_1, "delivery", self.tomorrow, self.tomorrow
            )
        )
        day_after = self.tomorrow + timedelta(days=1)
        self.assertTrue(
            self.Slot.available_slots(self.branch_1, "delivery", day_after, day_after)
        )
