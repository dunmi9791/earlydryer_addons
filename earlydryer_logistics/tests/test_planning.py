# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestPlanning(LogisticsCommon):
    def _stop(self, area, slot_index, lat=0.0, lng=0.0):
        partner = self.env["res.partner"].create(
            {
                "name": f"T {area.name} {lat}",
                "earlydryer_area_id": area.id,
                "partner_latitude": lat,
                "partner_longitude": lng,
            }
        )
        zone = self.Zone._earlydryer_find(self.branch_1, area)
        stop = self.Stop.create(
            {
                "stop_type": "pickup",
                "partner_id": partner.id,
                "earlydryer_branch_id": self.branch_1.id,
                "zone_id": zone.id,
            }
        )
        slots = self.Slot.available_slots(
            self.branch_1, "pickup", self.tomorrow, self.tomorrow
        )
        stop._earlydryer_set_slot(slots[slot_index]["key"])
        stop.action_schedule()
        return stop

    def _plan(self, riders, max_stops):
        wizard = (
            self.env["earlydryer.logistics.plan.wizard"]
            .with_user(self.user_manager)
            .create(
                {
                    "date": self.tomorrow,
                    "branch_id": self.branch_1.id,
                    "max_stops": max_stops,
                    "rider_employee_ids": [(6, 0, riders.ids)],
                }
            )
        )
        to_plan = self.Stop.search(
            [
                ("earlydryer_branch_id", "=", self.branch_1.id),
                ("state", "=", "scheduled"),
                ("trip_id", "=", False),
                ("slot_date", "=", self.tomorrow),
            ]
        )
        self.assertEqual(wizard.stop_count, len(to_plan))
        wizard.action_plan()
        return self.Trip.search(
            [
                ("date", "=", self.tomorrow),
                ("earlydryer_branch_id", "=", self.branch_1.id),
            ],
            order="id",
        )

    def test_groups_by_slot_and_zone_with_cap(self):
        morning_near = self._stop(self.area_near, 0) | self._stop(self.area_near, 0)
        morning_far = self._stop(self.area_far, 0)
        afternoon = self._stop(self.area_near, 1) | self._stop(self.area_mid, 1)
        trips = self._plan(self.emp_rider | self.emp_rider_2, 2)
        self.assertEqual(len(trips), 3)
        for trip in trips:
            self.assertLessEqual(len(trip.stop_ids), 2)
            self.assertEqual(len(set(trip.stop_ids.mapped("slot_start"))), 1)
            self.assertTrue(all(s.state == "assigned" for s in trip.stop_ids))
            self.assertEqual(trip.state, "draft")
        self.assertEqual(trips[0].stop_ids, morning_near)
        self.assertEqual(trips[1].stop_ids, morning_far)
        self.assertEqual(trips[2].stop_ids, afternoon)
        self.assertEqual(
            trips.mapped("rider_employee_id").ids,
            (self.emp_rider | self.emp_rider_2).ids,
        )
        self.assertEqual(trips[2].rider_employee_id, self.emp_rider)

    def test_nearest_neighbour_order(self):
        # plant at (9.0790, 7.4700); created far to near
        far = self._stop(self.area_near, 0, 9.1100, 7.4700)
        near = self._stop(self.area_near, 0, 9.0800, 7.4700)
        middle = self._stop(self.area_near, 0, 9.0950, 7.4700)
        no_gps = self._stop(self.area_near, 0)
        no_gps.write({"latitude": 0.0, "longitude": 0.0})
        trips = self._plan(self.emp_rider, 10)
        self.assertEqual(len(trips), 1)
        ordered = trips.stop_ids.sorted("sequence")
        self.assertEqual(ordered.ids, [near.id, middle.id, far.id, no_gps.id])
