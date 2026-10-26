# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import binascii
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.earlydryer_notifications.tools import phone_e164

from .earlydryer_logistics_stop import CLOSED_STATES, GROUPS

MAX_PHOTO_BYTES = 3 * 1024 * 1024
MAX_PHOTOS_PER_STOP = 8
MAX_SIGNATURE_BYTES = 512 * 1024


class EarlydryerLogisticsRiderApi(models.AbstractModel):
    """JSON-safe methods of the rider phone view ("My Trips").

    Every mutating method takes a client-generated UUID and is idempotent:
    the phone queues its actions offline and may send one twice. Riders only
    reach their own trips (record rules + checks below); the work is then done
    with sudo, so riders keep read-only access rights.
    """

    _name = "earlydryer.logistics.rider.api"
    _description = "Earlydryer Rider Phone API"

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    @api.model
    def _employees(self):
        return self.env["hr.employee"].sudo().search([("user_id", "=", self.env.uid)])

    @api.model
    def _check_trip(self, trip_id):
        trip = self.env["earlydryer.logistics.trip"].browse(int(trip_id)).exists()
        if not trip:
            raise UserError(self.env._("Trip not found."))
        trip.check_access("read")
        if not (
            trip._earlydryer_is_rider_of()
            or self.env["earlydryer.logistics.stop"]._earlydryer_has_right(
                "outcome", trip.earlydryer_branch_id
            )
        ):
            raise AccessError(self.env._("This is not one of your trips."))
        if trip.is_carrier:
            raise UserError(
                self.env._("3PL trips are recorded from the office, not the rider view.")
            )
        return trip.sudo()

    @api.model
    def _check_stop(self, stop_id):
        stop = self.env["earlydryer.logistics.stop"].browse(int(stop_id)).exists()
        if not stop:
            raise UserError(self.env._("Stop not found."))
        stop.check_access("read")
        if not stop.trip_id:
            raise UserError(self.env._("Stop %(stop)s is not on a trip.", stop=stop.name))
        self._check_trip(stop.trip_id.id)
        return stop.sudo()

    @api.model
    def _run(self, uuid, action, func, stop=None, trip=None):
        if not uuid or not re.fullmatch(r"[0-9A-Za-z\-]{8,64}", str(uuid)):
            raise UserError(self.env._("Invalid client action id."))
        return self.env["earlydryer.logistics.client.action"]._earlydryer_run(
            uuid, action, func, stop=stop, trip=trip
        )

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    @api.model
    def _stop_card(self, stop):
        address = stop._earlydryer_address().sudo()
        phone = phone_e164(stop.phone or stop.partner_id.phone or "")
        currency = stop.currency_id or self.env.company.currency_id
        jobs = stop.job_ids | stop.job_id
        return {
            "id": stop.id,
            "name": stop.name,
            "type": stop.stop_type,
            "state": stop.state,
            "sequence": stop.sequence,
            "attempt": stop.attempt,
            "customer": stop.partner_id.name,
            "address": stop.address_text or "",
            "area": stop.area_id.name or "",
            "landmark": stop.landmark or "",
            "gate": stop.gate_instructions or "",
            "slot": stop.slot_label or "",
            "phone": phone or "",
            "tel_url": f"tel:{phone}" if phone else False,
            "whatsapp_url": f"https://wa.me/{phone.lstrip('+')}" if phone else False,
            "map_url": stop.map_url or False,
            "has_location": bool(address.partner_latitude or address.partner_longitude),
            "cod_amount": stop.cod_amount,
            "currency": currency.symbol or "",
            "bag_count": stop.bag_count,
            "jobs": [job.name for job in jobs],
            "job_id": stop.job_id.id or False,
            "loaded": stop.loaded,
            "customer_note": stop.customer_note or "",
            "cash_collected": stop.cash_collected,
            "collection_method": stop.collection_method or False,
            "fail_reason": stop.fail_reason_id.name or "",
            "photo_count": len(stop.photo_ids),
            "credit_approved": bool(
                stop.stop_type == "delivery"
                and stop.job_id
                and stop.cod_amount
                and stop.job_id.sudo()._earlydryer_credit_approved(stop.cod_amount)
            ),
        }

    @api.model
    def _trip_card(self, trip):
        stops = trip.stop_ids.filtered(lambda s: s.state != "cancelled").sorted(
            lambda s: (s.sequence, s.id)
        )
        return {
            "id": trip.id,
            "name": trip.name,
            "date": fields.Date.to_string(trip.date),
            "slot": trip.slot or "",
            "state": trip.state,
            "branch": trip.earlydryer_branch_id.display_name,
            "vehicle": trip.vehicle_id.display_name or "",
            "has_vehicle": bool(trip.vehicle_id),
            "odometer_start": trip.odometer_start,
            "stop_count": len(stops),
            "done_count": len(stops.filtered(lambda s: s.state in CLOSED_STATES)),
            "cod_total": sum(stops.mapped("cod_amount")),
            "cash_collected": sum(stops.mapped("cash_collected")),
            "stops": [self._stop_card(stop) for stop in stops],
        }

    @api.model
    def _approvers(self, branches):
        """Employees who may approve credit at the door (PIN asked)."""
        group = self.env.ref(GROUPS["branch_manager"])
        employees = self.env["hr.employee"].sudo().search(
            [("user_id", "!=", False), ("pin", "!=", False)]
        )
        return [
            {"id": employee.id, "name": employee.name}
            for employee in employees
            if group in employee.user_id.all_group_ids
            and (
                not employee.earlydryer_branch_id
                or employee.earlydryer_branch_id in branches
            )
        ]

    @api.model
    def rider_data(self):
        """Today's (and still open) trips of the current rider."""
        if not self.env.user.has_group(GROUPS["rider"]):
            raise AccessError(self.env._("The rider view is for riders."))
        employees = self._employees()
        today = fields.Date.context_today(self)
        trips = self.env["earlydryer.logistics.trip"].sudo().search(
            [
                ("rider_employee_id", "in", employees.ids),
                ("carrier_partner_id", "=", False),
                "|",
                ("state", "=", "in_progress"),
                "&",
                ("state", "=", "planned"),
                ("date", "<=", today),
            ],
            order="date, id",
        )
        reasons = self.env["earlydryer.logistics.fail.reason"].search([])
        return {
            "server_time": fields.Datetime.to_string(fields.Datetime.now()),
            "rider": employees[:1].name or self.env.user.name,
            "trips": [self._trip_card(trip) for trip in trips],
            "fail_reasons": [
                {
                    "id": reason.id,
                    "name": reason.name,
                    "stop_type": reason.stop_type,
                    "note_required": reason.note_required,
                }
                for reason in reasons
            ],
            "approvers": self._approvers(trips.earlydryer_branch_id),
            "gps_threshold": self.env["earlydryer.logistics.stop"]._earlydryer_gps_threshold(),
        }

    # ------------------------------------------------------------------
    # Actions (idempotent per client UUID)
    # ------------------------------------------------------------------

    @api.model
    def rider_start_trip(self, uuid, trip_id, odometer=None):
        trip = self._check_trip(trip_id)

        def run():
            trip._earlydryer_start(odometer=odometer)
            return {"ok": True, "trip": self._trip_card(trip)}

        return self._run(uuid, "start", run, trip=trip)

    @api.model
    def rider_scan(self, uuid, trip_id, code):
        trip = self._check_trip(trip_id)

        def run():
            result = trip._earlydryer_scan(code)
            result["trip"] = self._trip_card(trip)
            return result

        return self._run(uuid, "scan", run, trip=trip)

    @api.model
    def rider_arrive(self, uuid, stop_id, gps=None, at=None):
        stop = self._check_stop(stop_id)

        def run():
            stop._earlydryer_arrive(gps=gps, at=at)
            return {"ok": True, "stop": self._stop_card(stop), **self._gps_flags(stop)}

        return self._run(uuid, "arrive", run, stop=stop)

    @api.model
    def _gps_flags(self, stop):
        return {
            "low_accuracy": stop.gps_low_accuracy,
            "accuracy": stop.gps_accuracy_m,
        }

    @api.model
    def rider_complete(self, uuid, stop_id, vals):
        """``vals``: see ``earlydryer.logistics.stop._earlydryer_complete``."""
        stop = self._check_stop(stop_id)
        allowed = {
            "recipient_name", "signature", "cash_collected", "collection_method",
            "transfer_amount", "approver_employee_id", "pin", "offline",
            "bag_count", "piece_count_estimate", "pickup_note", "gps", "done_on",
            "save_location", "fix_location",
        }
        vals = {key: value for key, value in (vals or {}).items() if key in allowed}
        signature = vals.get("signature")
        if signature:
            if "," in signature[:64]:
                signature = signature.split(",", 1)[1]
            try:
                raw = base64.b64decode(signature, validate=True)
            except (binascii.Error, ValueError) as error:
                raise UserError(self.env._("The signature could not be read.")) from error
            if len(raw) > MAX_SIGNATURE_BYTES:
                raise UserError(self.env._("The signature image is too large."))
            vals["signature"] = signature

        def run():
            stop._earlydryer_complete(vals)
            return {"ok": True, "stop": self._stop_card(stop), **self._gps_flags(stop)}

        return self._run(uuid, "complete", run, stop=stop)

    @api.model
    def rider_fail(self, uuid, stop_id, reason_id, note=None, gps=None, at=None):
        stop = self._check_stop(stop_id)
        reason = self.env["earlydryer.logistics.fail.reason"].browse(int(reason_id)).exists()

        def run():
            stop._earlydryer_fail(reason, note=note, gps=gps, at=at)
            return {"ok": True, "stop": self._stop_card(stop), **self._gps_flags(stop)}

        return self._run(uuid, "fail", run, stop=stop)

    @api.model
    def rider_check_pin(self, stop_id, employee_id, pin):
        """Online check of a manager PIN before handing over on credit (not
        recorded: the completion re-checks it)."""
        stop = self._check_stop(stop_id)
        employee = self.env["hr.employee"].sudo().browse(int(employee_id)).exists()
        return {"ok": bool(employee and stop._earlydryer_verify_pin(employee, pin))}

    @api.model
    def rider_upload_photo(self, uuid, stop_id, data, mimetype="image/jpeg", name=None):
        """One compressed photo of a stop, sent after the stop synced."""
        stop = self._check_stop(stop_id)
        if mimetype not in ("image/jpeg", "image/png", "image/webp"):
            raise UserError(self.env._("Only photos can be uploaded."))
        try:
            raw = base64.b64decode(data or "", validate=True)
        except (binascii.Error, ValueError) as error:
            raise UserError(self.env._("The photo could not be read.")) from error
        if not raw or len(raw) > MAX_PHOTO_BYTES:
            raise UserError(self.env._("The photo is empty or too large."))

        def run():
            if len(stop.photo_ids) >= MAX_PHOTOS_PER_STOP:
                raise UserError(self.env._("Too many photos on this stop."))
            attachment = self.env["ir.attachment"].sudo().create(
                {
                    "name": name or f"{stop.name.replace('/', '-')}-{len(stop.photo_ids) + 1}.jpg",
                    "datas": data,
                    "mimetype": mimetype,
                    "res_model": stop._name,
                    "res_id": stop.id,
                }
            )
            stop.photo_ids = [(4, attachment.id)]
            return {"ok": True, "attachment_id": attachment.id}

        return self._run(uuid, "photo", run, stop=stop)
