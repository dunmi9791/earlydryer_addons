# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime

from odoo.fields import Command
from odoo.tests import tagged

from .common import CatalogCommon

# Monday 2 November 2026, 08:00 UTC
MONDAY_8 = datetime(2026, 11, 2, 8, 0)


@tagged("post_install", "-at_install")
class TestPromisedDatetime(CatalogCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        attendances = [
            Command.create(
                {
                    "name": f"Day {day} {period}",
                    "dayofweek": str(day),
                    "hour_from": hour_from,
                    "hour_to": hour_to,
                    "day_period": period,
                }
            )
            for day in range(5)
            for hour_from, hour_to, period in (
                (8, 12, "morning"),
                (13, 17, "afternoon"),
            )
        ]
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "T Plant hours",
                "tz": "UTC",
                "attendance_ids": [Command.clear(), *attendances],
            }
        )
        cls.branch_1.resource_calendar_id = cls.calendar
        cls.branch_2.resource_calendar_id = False

    def _promise(self, items, branch, express=False):
        return self.Catalog.promised_datetime(
            items, branch, express=express, start=MONDAY_8
        )

    def test_with_calendar(self):
        # 16 working hours (8 h a day) -> Tuesday 17:00
        self.assertEqual(
            self._promise(self.svc_wi, self.branch_1), datetime(2026, 11, 3, 17)
        )
        # express 4 h -> Monday 12:00
        self.assertEqual(
            self._promise(self.svc_wi, self.branch_1, express=True),
            datetime(2026, 11, 2, 12),
        )
        # 40 h -> Friday 17:00
        self.assertEqual(
            self._promise(self.svc_rug, self.branch_1), datetime(2026, 11, 6, 17)
        )

    def test_without_calendar(self):
        self.assertEqual(
            self._promise(self.svc_wi, self.branch_2), datetime(2026, 11, 3, 0)
        )
        self.assertEqual(
            self._promise(self.svc_wi, self.branch_2, express=True),
            datetime(2026, 11, 2, 12),
        )
        self.assertEqual(self._promise(self.svc_wi, False), datetime(2026, 11, 3, 0))

    def test_multiple_service_types_latest(self):
        services = self.svc_wi | self.svc_dc | self.svc_rug
        self.assertEqual(
            self._promise(services, self.branch_1), datetime(2026, 11, 6, 17)
        )
        # express where available: WI 4 h, DC 8 h, rug has no express (40 h)
        self.assertEqual(
            self._promise(self.svc_wi | self.svc_dc, self.branch_1, express=True),
            datetime(2026, 11, 2, 17),
        )
        self.assertEqual(
            self._promise(services, self.branch_1, express=True),
            datetime(2026, 11, 6, 17),
        )

    def test_products_use_overrides(self):
        self.shirt_wi.earlydryer_turnaround_hours_override = 8
        self.assertEqual(
            self._promise(self.shirt_wi, self.branch_1), datetime(2026, 11, 2, 17)
        )
        self.assertEqual(
            self._promise(self.svc_wi, self.branch_1), datetime(2026, 11, 3, 17)
        )

    def test_default_start_now(self):
        self.assertTrue(self.Catalog.promised_datetime(self.svc_wi, self.branch_2))
        self.assertEqual(
            self.Catalog.promised_datetime(self.Service, self.branch_1, start=MONDAY_8),
            MONDAY_8,
        )
