# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Command

from .earlydryer_logistics_stop import STOP_CTX

MOVE_CTX = "earlydryer_stage_move"
WEEKDAYS = [str(day) for day in range(7)]
# morning, afternoon, evening (local time)
SLOTS = [("Morning", 8.0, 11.0), ("Afternoon", 12.0, 15.0), ("Evening", 16.0, 19.0)]


class EarlydryerLogisticsDemo(models.AbstractModel):
    _name = "earlydryer.logistics.demo"
    _description = "Earlydryer Logistics Demo Data"

    @api.model
    def _earlydryer_load_demo(self):
        """Demo only: zones, slots, riders, a vehicle, a 3PL and one day of
        pickups and deliveries (closed trip with a small shortage, a failed
        delivery rescheduled, a 3PL trip with its carrier bill)."""
        return self.sudo()._earlydryer_load_demo_sudo()

    def _earlydryer_load_demo_sudo(self):
        ref = self.env.ref
        branches = {
            "p1": ref("earlydryer_base.branch_plant_1"),
            "p2": ref("earlydryer_base.branch_plant_2"),
        }
        # plant locations (approximate): Wuse II and Gwarinpa
        branches["p1"].partner_id.write(
            {"partner_latitude": 9.0790, "partner_longitude": 7.4700}
        )
        branches["p2"].partner_id.write(
            {"partner_latitude": 9.1100, "partner_longitude": 7.4050}
        )
        self._demo_zones(branches)
        self._demo_slots(branches)
        riders, vehicle, carrier = self._demo_people(branches)
        self._demo_customers()
        self._demo_day(branches["p1"], riders, vehicle, carrier)
        return True

    def _area(self, name):
        return self.env.ref(f"earlydryer_logistics.area_{name}")

    def _demo_zones(self, branches):
        Zone = self.env["earlydryer.delivery.zone"]
        central = [
            "central_area",
            "wuse",
            "wuse_ii",
            "maitama",
            "garki",
            "asokoro",
            "utako",
            "jabi",
            "wuye",
            "mabushi",
        ]
        outer = ["gwarinpa", "kubwa", "life_camp", "katampe", "jahi", "dutse", "kado"]
        south = [
            "apo",
            "lugbe",
            "lokogoma",
            "galadimawa",
            "gudu",
            "durumi",
            "nyanya",
            "karu",
        ]
        for code, branch in branches.items():
            uplift = 0 if code == "p1" else 250
            Zone.create(
                [
                    {
                        "name": f"Central ({code.upper()})",
                        "earlydryer_branch_id": branch.id,
                        "sequence": 10,
                        "fee_mode": "flat",
                        "flat_fee": 1500 + uplift,
                        "express_fee": 1000,
                        "area_ids": [Command.set([self._area(a).id for a in central])],
                    },
                    {
                        "name": f"Outer by distance ({code.upper()})",
                        "earlydryer_branch_id": branch.id,
                        "sequence": 20,
                        "fee_mode": "distance",
                        "base_fee": 1000,
                        "fee_per_km": 150,
                        "max_km": 35,
                        "express_fee": 1500,
                        "min_order_amount": 3000,
                        "area_ids": [Command.set([self._area(a).id for a in outer])],
                    },
                    {
                        "name": f"South, free over 20,000 ({code.upper()})",
                        "earlydryer_branch_id": branch.id,
                        "sequence": 30,
                        "fee_mode": "flat",
                        "flat_fee": 2000 + uplift,
                        "express_fee": 1500,
                        "free_over_amount": 20000,
                        "area_ids": [Command.set([self._area(a).id for a in south])],
                    },
                ]
            )

    def _demo_slots(self, branches):
        Slot = self.env["earlydryer.logistics.slot.template"]
        Slot.create(
            [
                {
                    "name": name,
                    "earlydryer_branch_id": branch.id,
                    "weekday": day,
                    "start_time": start,
                    "end_time": end,
                    "stop_type": "both",
                    "capacity": 15,
                    "cutoff_hours": 2,
                }
                for branch in branches.values()
                for day in WEEKDAYS
                for name, start, end in SLOTS
            ]
        )

    def _demo_people(self, branches):
        ref = self.env.ref
        Employee = self.env["hr.employee"]
        rider_group = ref("earlydryer_base.group_rider")
        user_2 = self.env["res.users"].create(
            {
                "name": "Demo Rider 2 (P1)",
                "login": "ed_rider2",
                "password": "ed_rider2",
                "group_ids": [Command.set([rider_group.id])],
                "earlydryer_branch_ids": [Command.set([branches["p1"].id])],
                "earlydryer_branch_id": branches["p1"].id,
            }
        )
        riders = Employee.create(
            [
                {
                    "name": "Musa Rider",
                    "user_id": ref("earlydryer_base.user_rider").id,
                    "earlydryer_branch_id": branches["p1"].id,
                    "earlydryer_is_rider": True,
                    "mobile_phone": "+2348030000101",
                },
                {
                    "name": "Bola Rider",
                    "user_id": user_2.id,
                    "earlydryer_branch_id": branches["p1"].id,
                    "earlydryer_is_rider": True,
                    "mobile_phone": "+2348030000102",
                },
                {
                    "name": "Ike Rider (no login)",
                    "earlydryer_branch_id": branches["p2"].id,
                    "earlydryer_is_rider": True,
                    "mobile_phone": "+2348030000103",
                },
            ]
        )
        manager = ref("earlydryer_laundry_order.employee_branch_manager_p1")
        if not manager.pin:
            manager.pin = "4321"
        brand = self.env["fleet.vehicle.model.brand"].create({"name": "Bajaj (demo)"})
        model = self.env["fleet.vehicle.model"].create(
            {"name": "Boxer 150", "brand_id": brand.id, "vehicle_type": "bike"}
        )
        vehicle = self.env["fleet.vehicle"].create(
            {"model_id": model.id, "license_plate": "ABJ-123-ED"}
        )
        vehicle.odometer = 12500
        carrier = self.env["res.partner"].create(
            {
                "name": "Swift Dispatch Ltd (demo 3PL)",
                "is_company": True,
                "earlydryer_is_carrier": True,
                "phone": "+2349000000555",
                "city": "Abuja",
                "country_id": ref("base.ng").id,
            }
        )
        return riders, vehicle, carrier

    def _demo_customers(self):
        ref = self.env.ref
        data = {
            "adaeze": ("wuse_ii", "Behind Banex Plaza, white gate", 9.0812, 7.4685),
            "kabir": (
                "maitama",
                "Opposite the Transcorp Hilton side gate",
                9.0868,
                7.4931,
            ),
            "funmi": ("gwarinpa", "3rd Avenue, near the fire station", False, False),
            "samuel": (
                "lugbe",
                "Off airport road, after the filling station",
                8.9815,
                7.3790,
            ),
        }
        for name, (area, landmark, lat, lng) in data.items():
            partner = ref(f"earlydryer_laundry_order.partner_customer_{name}")
            partner.write(
                {
                    "earlydryer_area_id": self._area(area).id,
                    "earlydryer_landmark": landmark,
                    "earlydryer_gate_instructions": "Call on arrival",
                    "partner_latitude": lat or 0.0,
                    "partner_longitude": lng or 0.0,
                }
            )

    # ------------------------------------------------------------------
    # One demo day
    # ------------------------------------------------------------------

    def _slot(self, stop, day, index=0):
        """Put a demo stop on a slot without availability checks (the demo
        day may be in the past)."""
        Slot = self.env["earlydryer.logistics.slot.template"]
        template = Slot.search(
            [
                ("earlydryer_branch_id", "=", stop.earlydryer_branch_id.id),
                ("weekday", "=", str(day.weekday())),
            ],
            order="start_time",
        )[index]
        start, end = template._earlydryer_bounds(day)
        stop.with_context(**{STOP_CTX: True}).write(
            {
                "slot_template_id": template.id,
                "slot_date": day,
                "slot_start": start,
                "slot_end": end,
            }
        )

    def _stop(self, stop_type, partner, branch, day, job=None, slot=0, **vals):
        Quote = self.env["earlydryer.logistics.quote"]
        quote = Quote.quote(
            partner,
            partner,
            branch,
            stop_type,
            day,
            order_amount=job.amount_total if job else 0.0,
        )
        stop = self.env["earlydryer.logistics.stop"].create(
            {
                "stop_type": stop_type,
                "partner_id": partner.id,
                "address_partner_id": partner.id,
                "earlydryer_branch_id": branch.id,
                "job_id": job.id if job else False,
                "zone_id": quote["zone_id"],
                "distance_km": quote["distance_km"] or 0.0,
                "source": vals.pop("source", "phone"),
                **vals,
            }
        )
        stop.with_context(**{STOP_CTX: True}).fee_amount = quote["fee"]
        self._slot(stop, day, slot)
        stop.action_schedule()
        return stop

    def _ready_job(self, partner, branch, lines, paid=False):
        ref = self.env.ref
        catalog = self.env["earlydryer.catalog"]
        order = self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "earlydryer_branch_id": branch.id,
                "earlydryer_channel": "phone",
                "earlydryer_fulfilment": "deliver",
                "order_line": [
                    Command.create(
                        {
                            "product_id": catalog.get_laundry_product(
                                ref(
                                    f"earlydryer_service_catalog.garment_category_{cat}"
                                ),
                                ref(f"earlydryer_service_catalog.service_type_{svc}"),
                            ).id,
                            "product_uom_qty": qty,
                        }
                    )
                    for cat, svc, qty in lines
                ],
            }
        )
        order.action_confirm()
        job = order.laundry_job_ids
        if paid:
            invoice = order._create_invoices()
            invoice.action_post()
            # paid in cash at the plant: straight to the cash account (like
            # the wallet top-ups), matched with the invoice
            journal = branch.cash_journal_id
            payment = self.env["account.payment"].create(
                {
                    "payment_type": "inbound",
                    "partner_type": "customer",
                    "partner_id": invoice.commercial_partner_id.id,
                    "amount": invoice.amount_residual,
                    "journal_id": journal.id,
                    "payment_method_line_id": journal.inbound_payment_method_line_ids[
                        :1
                    ].id,
                    "force_outstanding_account_id": journal.default_account_id.id,
                }
            )
            payment.action_post()
            (payment.move_id.line_ids | invoice.line_ids).filtered(
                lambda line: (
                    line.account_id.account_type == "asset_receivable"
                    and not line.reconciled
                )
            ).reconcile()
        # demo shortcut through production: straight to the shelf
        job.with_context(**{MOVE_CTX: True}).write(
            {
                "state": "ready",
                "shelf_id": branch.shelf_ids[:1].id,
                "ready_on": fields.Datetime.now(),
            }
        )
        return job

    def _demo_day(self, branch, riders, vehicle, carrier):
        ref = self.env.ref
        today = fields.Date.context_today(self)
        tomorrow = today + timedelta(days=1)
        customer = lambda name: ref(f"earlydryer_laundry_order.partner_customer_{name}")  # noqa: E731
        Trip = self.env["earlydryer.logistics.trip"]
        absent = ref("earlydryer_logistics.fail_reason_absent")

        # booked pickups for tomorrow
        self._stop(
            "pickup", customer("funmi"), branch, tomorrow, slot=0, source="whatsapp"
        )
        self._stop("pickup", customer("samuel"), branch, tomorrow, slot=1)

        # today's trip of Musa: one pickup, two COD deliveries
        pickup = self._stop(
            "pickup",
            customer("kabir"),
            branch,
            today,
            slot=0,
            return_delivery=True,
            customer_note="Two suits, handle with care",
        )
        job_cod = self._ready_job(
            customer("adaeze"),
            branch,
            [("shirt", "wash_iron", 5), ("trouser", "wash_iron", 2)],
        )
        delivery_cod = self._stop(
            "delivery", customer("adaeze"), branch, today, job_cod, slot=1
        )
        job_fail = self._ready_job(
            customer("samuel"), branch, [("shirt", "wash_iron", 3)]
        )
        delivery_fail = self._stop(
            "delivery", customer("samuel"), branch, today, job_fail, slot=1
        )
        trip = Trip.create(
            {
                "earlydryer_branch_id": branch.id,
                "date": today,
                "slot": "Morning run",
                "rider_employee_id": riders[0].id,
                "vehicle_id": vehicle.id,
            }
        )
        for sequence, stop in enumerate([pickup, delivery_cod, delivery_fail], 1):
            stop.write({"trip_id": trip.id, "sequence": sequence * 10})
        trip.action_plan()
        trip._earlydryer_start(odometer=12500)
        trip._earlydryer_scan(job_cod.name)
        trip._earlydryer_scan(job_fail.name)
        gps = {"lat": 9.0868, "lng": 7.4931, "accuracy": 18}
        pickup._earlydryer_arrive(gps=gps)
        pickup._earlydryer_complete(
            {
                "recipient_name": "Kabir",
                "bag_count": 2,
                "piece_count_estimate": 6,
                "pickup_note": "Seal 0042",
                "gps": gps,
            }
        )
        delivery_cod._earlydryer_arrive(
            gps={"lat": 9.0812, "lng": 7.4685, "accuracy": 12}
        )
        delivery_cod._earlydryer_complete(
            {
                "recipient_name": "Adaeze",
                "collection_method": "cash",
                "cash_collected": delivery_cod.cod_amount,
            }
        )
        delivery_fail._earlydryer_arrive(
            gps={"lat": 8.9815, "lng": 7.3790, "accuracy": 140}
        )
        delivery_fail._earlydryer_fail(absent, note="No answer at the gate, phone off")
        retry = self.env["earlydryer.logistics.stop"].browse(
            delivery_fail.action_reschedule()["res_id"]
        )
        self._slot(retry, tomorrow, 1)
        retry.action_schedule()
        # the rider hands over 200 less than collected: shortage posted
        trip._earlydryer_close(trip.cash_expected - 200, odometer_end=12538)

        # the pickup is priced in the backend: job created, delivery back
        order_action = pickup.action_price_backend()
        order = self.env["sale.order"].browse(order_action["res_id"])
        catalog = self.env["earlydryer.catalog"]
        order.write(
            {
                "order_line": [
                    Command.create(
                        {
                            "product_id": catalog.get_laundry_product(
                                ref("earlydryer_service_catalog.garment_category_suit"),
                                ref(
                                    "earlydryer_service_catalog.service_type_dry_cleaning"
                                ),
                            ).id,
                            "product_uom_qty": 2,
                        }
                    )
                ]
            }
        )
        order.action_confirm()

        # a 3PL trip with a paid job and its carrier bill
        job_3pl = self._ready_job(
            customer("funmi"), branch, [("shirt", "wash_iron", 4)], paid=True
        )
        delivery_3pl = self._stop(
            "delivery", customer("funmi"), branch, today, job_3pl, slot=2
        )
        trip_3pl = Trip.create(
            {
                "earlydryer_branch_id": branch.id,
                "date": today,
                "slot": "Evening 3PL",
                "carrier_partner_id": carrier.id,
                "carrier_reference": "SWD-0001",
                "carrier_fee": 3000,
            }
        )
        delivery_3pl.write({"trip_id": trip_3pl.id})
        trip_3pl.action_plan()
        trip_3pl._earlydryer_start()
        # the carrier collected the delivery fee and handed it over
        delivery_3pl._earlydryer_complete(
            {
                "recipient_name": "Funmi (via carrier)",
                "collection_method": "cash",
                "cash_collected": delivery_3pl.cod_amount,
            }
        )
        trip_3pl._earlydryer_close(trip_3pl.cash_expected)
        trip_3pl.action_create_carrier_bill()
        return True
