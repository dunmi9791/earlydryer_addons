# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta

from odoo import fields
from odoo.fields import Command

from odoo.addons.earlydryer_accounting_ng.tests.common import AccountingCommon

from ..models.earlydryer_logistics_stop import STOP_CTX


class LogisticsCommon(AccountingCommon):
    """Plant 1 (accounting set up) with areas, zones, slots, riders and a
    customer in a served area."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Stop = cls.env["earlydryer.logistics.stop"]
        cls.Trip = cls.env["earlydryer.logistics.trip"]
        cls.Zone = cls.env["earlydryer.delivery.zone"]
        cls.Area = cls.env["earlydryer.area"]
        cls.Slot = cls.env["earlydryer.logistics.slot.template"]
        cls.Quote = cls.env["earlydryer.logistics.quote"]
        cls.Api = cls.env["earlydryer.logistics.rider.api"]
        cls.Message = cls.env["earlydryer.notify.message"]
        cls.Alert = cls.env["earlydryer.notify.alert"]
        cls.reason_absent = cls.env.ref("earlydryer_logistics.fail_reason_absent")
        cls.reason_unable = cls.env.ref("earlydryer_logistics.fail_reason_unable_to_pay")
        cls.env["ir.config_parameter"].sudo().set_param(
            "earlydryer_logistics.road_factor", "1.3"
        )
        # plant 1 in Wuse II
        cls.branch_1.partner_id = cls.env["res.partner"].create(
            {
                "name": "T Plant 1",
                "partner_latitude": 9.0790,
                "partner_longitude": 7.4700,
            }
        )
        cls.area_near = cls.Area.create(
            {"name": "T Near", "latitude": 9.0810, "longitude": 7.4690}
        )
        cls.area_far = cls.Area.create(
            {"name": "T Far", "latitude": 9.1550, "longitude": 7.3220}
        )
        cls.area_mid = cls.Area.create(
            {"name": "T Mid", "latitude": 9.0300, "longitude": 7.4900}
        )
        cls.area_unserved = cls.Area.create({"name": "T Nowhere"})
        cls.zone_flat = cls.Zone.create(
            {
                "name": "T Flat",
                "earlydryer_branch_id": cls.branch_1.id,
                "sequence": 1,
                "fee_mode": "flat",
                "flat_fee": 1500,
                "express_fee": 1000,
                "area_ids": [Command.set(cls.area_near.ids)],
            }
        )
        cls.zone_distance = cls.Zone.create(
            {
                "name": "T Distance",
                "earlydryer_branch_id": cls.branch_1.id,
                "sequence": 2,
                "fee_mode": "distance",
                "base_fee": 1000,
                "fee_per_km": 100,
                "max_km": 40,
                "area_ids": [Command.set(cls.area_far.ids)],
            }
        )
        cls.zone_free = cls.Zone.create(
            {
                "name": "T Free over",
                "earlydryer_branch_id": cls.branch_1.id,
                "sequence": 3,
                "fee_mode": "flat",
                "flat_fee": 2000,
                "express_fee": 500,
                "free_over_amount": 10000,
                "min_order_amount": 3000,
                "area_ids": [Command.set(cls.area_mid.ids)],
            }
        )
        cls.Slot.create(
            [
                {
                    "name": name,
                    "earlydryer_branch_id": cls.branch_1.id,
                    "weekday": str(day),
                    "start_time": start,
                    "end_time": end,
                    "capacity": 5,
                    "cutoff_hours": 2,
                }
                for day in range(7)
                for name, start, end in (("Morning", 8, 12), ("Afternoon", 13, 17))
            ]
        )
        cls.partner.write(
            {
                "earlydryer_area_id": cls.area_near.id,
                "earlydryer_landmark": "T blue gate",
                "partner_latitude": 9.0815,
                "partner_longitude": 7.4688,
                "earlydryer_notify_opt_in": True,
            }
        )
        cls.user_cs = cls._new_user(
            "t_customer_service", "earlydryer_base.group_customer_service", cls.branch_1
        )
        cls.user_ops = cls._new_user(
            "t_operations", "earlydryer_base.group_operations_manager", cls.branch_1
        )
        cls.user_rider = cls._new_user("t_rider", "earlydryer_base.group_rider", cls.branch_1)
        cls.user_rider_2 = cls._new_user(
            "t_rider_2", "earlydryer_base.group_rider", cls.branch_1
        )
        cls.emp_rider = cls.env["hr.employee"].create(
            {
                "name": "T Rider",
                "user_id": cls.user_rider.id,
                "earlydryer_branch_id": cls.branch_1.id,
                "earlydryer_is_rider": True,
            }
        )
        cls.emp_rider_2 = cls.env["hr.employee"].create(
            {
                "name": "T Rider 2",
                "user_id": cls.user_rider_2.id,
                "earlydryer_branch_id": cls.branch_1.id,
                "earlydryer_is_rider": True,
            }
        )
        cls.emp_rider_offline = cls.env["hr.employee"].create(
            {"name": "T Rider no login", "earlydryer_is_rider": True}
        )
        cls.tomorrow = fields.Date.context_today(cls.Stop) + timedelta(days=1)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sale_job(self, paid=False, partner=None, qty=1):
        job = self._create_job(
            [(self.shirt_wi, qty, None)],
            channel="phone",
            fulfilment="deliver",
            partner=partner,
        )
        if paid:
            invoice = job.sale_order_id._create_invoices()
            invoice.action_post()
            self.env["account.payment.register"].with_context(
                active_model="account.move", active_ids=invoice.ids
            ).create({"journal_id": self.bank_journal.id})._create_payments()
        return self._make_ready(job)

    def _pos_job(self, account=0.0):
        """A POS job paid in cash (or partly on the customer account)."""
        price = self._price(self.shirt_wi)
        order = self._sync(
            self._payload([self._line(self.shirt_wi, 1, price)], account=account)
        )
        return self._make_ready(order.earlydryer_job_id)

    def _first_slot_key(self, stop_type="delivery", day=None):
        slots = self.Slot.available_slots(
            self.branch_1, stop_type, day or self.tomorrow, day or self.tomorrow
        )
        return slots[0]["key"]

    def _book(self, stop_type, job=None, user=None, partner=None, **wizard_vals):
        """Book through the wizard (quote, first slot, schedule)."""
        user = user or self.user_front_desk
        Wizard = self.env["earlydryer.logistics.schedule.wizard"].with_user(user)
        context = {"default_job_id": job.id} if job else {}
        wizard = Wizard.with_context(**context).create(
            {
                "stop_type": stop_type,
                "partner_id": (partner or self.partner).id,
                "branch_id": self.branch_1.id,
                "date": self.tomorrow,
                **wizard_vals,
            }
        )
        wizard._earlydryer_apply_quote()
        for key, value in wizard_vals.items():
            if key in ("fee_amount", "fee_waived", "fee_waive_reason"):
                wizard[key] = value
        wizard.slot_line_ids[:1].selected = True
        action = wizard.action_confirm()
        return self.Stop.browse(action["res_id"])

    def _trip(self, stops, rider=None, carrier=None, start=True, **vals):
        trip = self.Trip.with_user(self.user_manager).create(
            {
                "earlydryer_branch_id": self.branch_1.id,
                "date": self.tomorrow,
                "rider_employee_id": (rider or self.emp_rider).id if not carrier else False,
                "carrier_partner_id": carrier.id if carrier else False,
                **vals,
            }
        )
        stops.with_user(self.user_manager).write({"trip_id": trip.id})
        trip.with_user(self.user_manager).action_plan()
        if start:
            trip.with_user(self.user_manager).action_start()
        return trip

    def _load(self, trip, job, user=None):
        """The rider scans the bag label (job number) onto the trip."""
        return self.Api.with_user(user or self.user_rider).rider_scan(
            self._uuid(), trip.id, job.name
        )

    _counter = [0]

    def _uuid(self):
        self._counter[0] += 1
        return f"00000000-0000-4000-8000-{self._counter[0]:012d}"

    def _messages(self, code, record):
        event = self.env["earlydryer.notify.event"].search([("code", "=", code)])
        return self.Message.search(
            [
                ("event_id", "=", event.id),
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
            ]
        )

    def _alerts(self, xmlid, record):
        rule = self.env.ref(xmlid)
        return self.Alert.search(
            [
                ("rule_id", "=", rule.id),
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
            ]
        )

    def _engine(self, stop):
        return stop.with_context(**{STOP_CTX: True})
