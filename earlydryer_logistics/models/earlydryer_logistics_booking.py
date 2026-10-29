# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL, consteq

from odoo.addons.earlydryer_notifications.tools import phone_e164

from .earlydryer_logistics_stop import OPEN_STATES, STOP_CTX, TODO_ACTIVITY

ONLINE_SOURCES = ("website", "app")
PARAM_MAX_OPEN = "earlydryer_logistics.online_max_open_pickups"
DEFAULT_MAX_OPEN = 3
QUOTE_DAYS = 7


class EarlydryerLogisticsBooking(models.AbstractModel):
    """Pickups ordered online (website, mobile app through earlydryer_api).

    The only public entry point: callers are anonymous or portal users, so
    every method works as superuser and checks its input itself. The fee
    always comes from the quote, never from the caller. Every value returned
    is JSON-safe.
    """

    _name = "earlydryer.logistics.booking"
    _description = "Earlydryer Online Pickup Booking"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_area(self, area_id):
        area = self.env["earlydryer.area"].sudo().browse(int(area_id or 0)).exists()
        if not area:
            raise UserError(self.env._("Choose your area."))
        return area

    @api.model
    def _earlydryer_zone_for_area(self, area):
        """Zone serving ``area`` (lowest sequence over all plants), or empty."""
        return (
            self.env["earlydryer.delivery.zone"]
            .sudo()
            .search(
                [
                    ("area_ids", "in", area.ids),
                    ("earlydryer_branch_id.active", "=", True),
                ],
                order="sequence, id",
                limit=1,
            )
        )

    @api.model
    def _earlydryer_address_values(self, payload, area):
        values = {
            "street": (payload.get("street") or "").strip(),
            "earlydryer_area_id": area.id,
            "earlydryer_landmark": (payload.get("landmark") or "").strip() or False,
            "earlydryer_gate_instructions": (
                payload.get("gate_instructions") or ""
            ).strip()
            or False,
            "city_id": area.city_id.id or False,
        }
        if payload.get("latitude") and payload.get("longitude"):
            values.update(
                partner_latitude=float(payload["latitude"]),
                partner_longitude=float(payload["longitude"]),
            )
        return values

    @api.model
    def _earlydryer_quote_values(self, area, zone, payload, date_from, days):
        """Quote for an address that may not exist yet (a new record)."""
        Partner = self.env["res.partner"].sudo()
        address = Partner.new(self._earlydryer_address_values(payload, area))
        return self.env["earlydryer.logistics.quote"].sudo().quote(
            address,
            address,
            zone.earlydryer_branch_id,
            "pickup",
            date_from,
            days=days,
        )

    @api.model
    def _earlydryer_find_customer(self, payload):
        """Customer matched by phone (commercial partner), else a new one."""
        Partner = self.env["res.partner"].sudo()
        phone = phone_e164((payload.get("phone") or "").strip())
        if not phone:
            raise UserError(self.env._("Enter a valid phone number."))
        name = (payload.get("name") or "").strip()
        candidates = Partner.search(
            [("phone", "ilike", phone[-4:]), ("type", "=", "contact")],
            order="id",
        )
        partner = candidates.filtered(lambda p: phone_e164(p.phone) == phone)[
            :1
        ].commercial_partner_id
        if partner:
            return partner
        if not name:
            raise UserError(self.env._("Enter your name."))
        return Partner.create(
            {
                "name": name,
                "phone": phone,
                "email": (payload.get("email") or "").strip() or False,
                "earlydryer_notify_opt_in": bool(payload.get("notify_opt_in")),
            }
        )

    @api.model
    def _earlydryer_find_address(self, customer, payload, area):
        """The customer itself when it has no address yet, a matching delivery
        address, else a new delivery address."""
        values = self._earlydryer_address_values(payload, area)
        if not values["street"]:
            raise UserError(self.env._("Enter your street address."))
        street = values["street"].lower()
        for contact in customer | customer.child_ids.filtered(
            lambda c: c.type == "delivery"
        ):
            if (
                contact.earlydryer_area_id == area
                and (contact.street or "").strip().lower() == street
            ):
                return contact
        if not customer.street and not customer.earlydryer_area_id:
            customer.write(values)
            return customer
        return (
            self.env["res.partner"]
            .sudo()
            .create(
                dict(
                    values,
                    parent_id=customer.id,
                    type="delivery",
                    name=customer.name,
                    phone=customer.phone,
                )
            )
        )

    @api.model
    def _earlydryer_lock_slot(self, key):
        """Lock the slot template row so that concurrent bookings cannot both
        take its last place."""
        Slot = self.env["earlydryer.logistics.slot.template"].sudo()
        template, _day = Slot._earlydryer_parse_key(key)
        if template:
            self.env.cr.execute(
                SQL(
                    "SELECT id FROM earlydryer_logistics_slot_template "
                    "WHERE id = %s FOR UPDATE",
                    template.id,
                )
            )
        return template

    @api.model
    def _earlydryer_max_open(self):
        value = (
            self.env["ir.config_parameter"].sudo().get_param(PARAM_MAX_OPEN) or ""
        )
        try:
            return int(value) if value else DEFAULT_MAX_OPEN
        except ValueError:
            return DEFAULT_MAX_OPEN

    @api.model
    def _earlydryer_find_stop(self, reference, token):
        stop = (
            self.env["earlydryer.logistics.stop"]
            .sudo()
            .search(
                [("name", "=", reference or ""), ("stop_type", "=", "pickup")],
                limit=1,
            )
        )
        if not stop or not token or not consteq(stop.access_token or "", token):
            raise UserError(self.env._("Pickup not found."))
        return stop

    @api.model
    def _earlydryer_stop_values(self, stop):
        return {
            "reference": stop.name,
            "access_token": stop.access_token or "",
            "state": stop.state,
            "state_label": dict(
                stop._fields["state"]._description_selection(self.env)
            )[stop.state],
            "plant": stop.earlydryer_branch_id.name,
            "plant_phone": stop.earlydryer_branch_id.phone or "",
            "slot_label": stop.slot_label or "",
            "slot_start": fields.Datetime.to_string(stop.slot_start) or "",
            "fee": stop.fee_amount,
            "currency": stop.currency_id.name,
            "address": stop.address_text or "",
            "area": stop.area_id.name or "",
            "cancellable": self._earlydryer_cancellable(stop),
        }

    @api.model
    def _earlydryer_cancellable(self, stop):
        if not stop.access_token or stop.state not in ("draft", "scheduled"):
            return False
        if stop.state == "draft" or not stop.slot_start:
            return True
        cutoff = timedelta(hours=stop.slot_template_id.cutoff_hours or 0)
        return stop.slot_start - cutoff > fields.Datetime.now()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @api.model
    def public_areas(self):
        """Areas served by at least one plant: ``[{"id", "name", "city"}]``."""
        zones = self.env["earlydryer.delivery.zone"].sudo().search(
            [("earlydryer_branch_id.active", "=", True)]
        )
        return [
            {"id": area.id, "name": area.name, "city": area.city_id.name or ""}
            for area in zones.area_ids.sorted("name")
        ]

    @api.model
    def quote_pickup(self, payload):
        """Fee and slots of a pickup at an address.

        :param payload: ``{"area_id", "street"?, "latitude"?, "longitude"?,
            "date"?, "days"?}``
        :returns: ``{"served", "fee", "currency", "plant", "message",
            "slots": [{"key", "label", "start", "end", "remaining"}]}``
        """
        area = self._earlydryer_area(payload.get("area_id"))
        zone = self._earlydryer_zone_for_area(area)
        if not zone:
            return {
                "served": False,
                "fee": 0.0,
                "currency": self.env.company.currency_id.name,
                "plant": "",
                "message": self.env._(
                    "We do not pick up in %(area)s yet. Ask us to call you back.",
                    area=area.name,
                ),
                "slots": [],
            }
        days = min(max(int(payload.get("days") or QUOTE_DAYS), 1), 14)
        date_from = payload.get("date") or fields.Date.context_today(self)
        quote = self._earlydryer_quote_values(area, zone, payload, date_from, days)
        branch = zone.earlydryer_branch_id
        return {
            "served": quote["served"],
            "fee": quote["fee"],
            "currency": branch.company_id.currency_id.name,
            "plant": branch.name,
            "message": quote["message"],
            "slots": [
                {
                    "key": slot["key"],
                    "label": slot["label"],
                    "start": slot["start"],
                    "end": slot["end"],
                    "remaining": slot["remaining"],
                }
                for slot in quote["available_slots"]
            ]
            if quote["served"]
            else [],
        }

    @api.model
    def book_pickup(self, payload):
        """Book and schedule a pickup ordered online.

        :param payload: ``{"name", "phone", "email"?, "area_id", "street",
            "landmark"?, "gate_instructions"?, "latitude"?, "longitude"?,
            "slot_key", "note"?, "return_delivery"?, "source"
            ("website" / "app"), "client_ref"? (idempotency key)}``
        :returns: the pickup (see ``get_pickup``)
        :raises UserError: not served, slot taken, invalid input
        """
        Stop = self.env["earlydryer.logistics.stop"].sudo()
        source = payload.get("source") or "website"
        if source not in ONLINE_SOURCES:
            raise UserError(self.env._("Unknown booking source."))
        client_ref = (payload.get("client_ref") or "").strip()[:64] or False
        if client_ref:
            existing = Stop.search(
                [("source", "=", source), ("client_ref", "=", client_ref)], limit=1
            )
            if existing:
                return self._earlydryer_stop_values(existing)
        area = self._earlydryer_area(payload.get("area_id"))
        zone = self._earlydryer_zone_for_area(area)
        if not zone:
            raise UserError(
                self.env._("We do not pick up in %(area)s yet.", area=area.name)
            )
        key = payload.get("slot_key") or ""
        template = self._earlydryer_lock_slot(key)
        if not template or template.earlydryer_branch_id != zone.earlydryer_branch_id:
            raise UserError(self.env._("Choose one of the times offered."))
        customer = self._earlydryer_find_customer(payload)
        open_count = Stop.search_count(
            [
                ("partner_id", "child_of", customer.id),
                ("source", "in", ONLINE_SOURCES),
                ("stop_type", "=", "pickup"),
                ("state", "in", OPEN_STATES),
            ]
        )
        if open_count >= self._earlydryer_max_open():
            raise UserError(
                self.env._(
                    "You already have %(count)s pickups booked: call us to book "
                    "another one.",
                    count=open_count,
                )
            )
        address = self._earlydryer_find_address(customer, payload, area)
        day = Stop.env["earlydryer.logistics.slot.template"]._earlydryer_parse_key(
            key
        )[1]
        quote = self.env["earlydryer.logistics.quote"].sudo().quote(
            customer, address, zone.earlydryer_branch_id, "pickup", day, days=1
        )
        if not quote["served"]:
            raise UserError(quote["message"] or self.env._("Address not served."))
        stop = Stop.with_context(**{STOP_CTX: True}).create(
            {
                "stop_type": "pickup",
                "source": source,
                "client_ref": client_ref,
                "access_token": uuid.uuid4().hex,
                "partner_id": customer.id,
                "address_partner_id": address.id,
                "earlydryer_branch_id": zone.earlydryer_branch_id.id,
                "zone_id": quote["zone_id"] or zone.id,
                "distance_km": quote["distance_km"] or 0.0,
                "quote_message": (quote["message"] or "")[:255] or False,
                "fee_amount": quote["fee"],
                "customer_note": (payload.get("note") or "").strip() or False,
                "return_delivery": bool(payload.get("return_delivery")),
            }
        )
        stop._earlydryer_set_slot(key)
        stop.action_schedule()
        stop._earlydryer_notify_online_booked()
        return self._earlydryer_stop_values(stop)

    @api.model
    def request_callback(self, payload):
        """Address not served or no time suits: a draft pickup and a To Do for
        Customer Service to call the customer back. No fee, no message."""
        Stop = self.env["earlydryer.logistics.stop"].sudo()
        source = payload.get("source") or "website"
        if source not in ONLINE_SOURCES:
            raise UserError(self.env._("Unknown booking source."))
        area = self._earlydryer_area(payload.get("area_id"))
        zone = self._earlydryer_zone_for_area(area)
        branch = zone.earlydryer_branch_id or self.env[
            "earlydryer.branch"
        ].sudo().search([], order="sequence, id", limit=1)
        if not branch:
            raise UserError(self.env._("No plant takes online requests."))
        customer = self._earlydryer_find_customer(payload)
        address = self._earlydryer_find_address(customer, payload, area)
        stop = Stop.with_context(**{STOP_CTX: True}).create(
            {
                "stop_type": "pickup",
                "source": source,
                "access_token": uuid.uuid4().hex,
                "partner_id": customer.id,
                "address_partner_id": address.id,
                "earlydryer_branch_id": branch.id,
                "zone_id": zone.id or False,
                "customer_note": (payload.get("note") or "").strip() or False,
                "return_delivery": bool(payload.get("return_delivery")),
            }
        )
        users = stop._earlydryer_callback_users()
        for user in users:
            stop.activity_schedule(
                TODO_ACTIVITY,
                summary=self.env._(
                    "Call back %(customer)s for an online pickup request",
                    customer=customer.name,
                ),
                note=stop.customer_note,
                user_id=user.id,
            )
        return self._earlydryer_stop_values(stop)

    @api.model
    def get_pickup(self, reference, token):
        stop = self._earlydryer_find_stop(reference, token)
        return self._earlydryer_stop_values(stop)

    @api.model
    def cancel_pickup(self, reference, token):
        """Cancel a pickup still scheduled, before its slot's cut-off."""
        stop = self._earlydryer_find_stop(reference, token)
        if not self._earlydryer_cancellable(stop):
            raise UserError(
                self.env._(
                    "Pickup %(stop)s can no longer be cancelled online: call "
                    "%(phone)s.",
                    stop=stop.name,
                    phone=stop.earlydryer_branch_id.phone or self.env._("the plant"),
                )
            )
        stop.action_cancel()
        stop.message_post(
            body=self.env._("Cancelled online by the customer."),
            subtype_xmlid="mail.mt_note",
        )
        return self._earlydryer_stop_values(stop)

    @api.model
    def customer_pickups(self, partner, limit=20):
        """Online and other pickups of a portal customer, newest first."""
        stops = self.env["earlydryer.logistics.stop"].sudo().search(
            [
                ("partner_id", "child_of", partner.commercial_partner_id.id),
                ("stop_type", "=", "pickup"),
            ],
            order="id desc",
            limit=limit,
        )
        return [self._earlydryer_stop_values(stop) for stop in stops]
