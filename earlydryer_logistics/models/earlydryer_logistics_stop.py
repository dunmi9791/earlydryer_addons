# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command, Domain

from odoo.addons.earlydryer_base.models.earlydryer_approval_request import (
    INTERNAL_CTX,
)

_logger = logging.getLogger(__name__)

STOP_TYPES = [("pickup", "Pickup"), ("delivery", "Delivery")]
STATES = [
    ("draft", "Draft"),
    ("scheduled", "Scheduled"),
    ("assigned", "Assigned"),
    ("en_route", "En Route"),
    ("arrived", "Arrived"),
    ("done", "Done"),
    ("failed", "Failed"),
    ("cancelled", "Cancelled"),
]
# a stop on its way: it holds its trip and, for deliveries, the garments
ACTIVE_STATES = ("assigned", "en_route", "arrived")
OPEN_STATES = ("draft", "scheduled", "assigned", "en_route", "arrived")
CLOSED_STATES = ("done", "failed", "cancelled")
COLLECTION_METHODS = [
    ("cash", "Cash"),
    ("transfer_confirmed", "Transfer Confirmed"),
    ("none", "Nothing Collected"),
]
SOURCES = [
    ("backend", "Backend"),
    ("whatsapp", "WhatsApp"),
    ("phone", "Phone"),
    ("website", "Website"),
    ("corporate", "Corporate"),
]
# context key: the stop engine writes the protected fields
STOP_CTX = "earlydryer_logistics_stop_engine"
# context key: a job goes back to Ready after a failed delivery (no new
# draft delivery is created for it)
FAILED_CTX = "earlydryer_logistics_failed_delivery"
PARAM_GPS_ACCURACY = "earlydryer_logistics.gps_accuracy_m"
DEFAULT_GPS_ACCURACY = 100.0
TODO_ACTIVITY = "mail.mail_activity_data_todo"

GROUPS = {
    "front_desk": "earlydryer_base.group_front_desk",
    "customer_service": "earlydryer_base.group_customer_service",
    "rider": "earlydryer_base.group_rider",
    "branch_manager": "earlydryer_base.group_branch_manager",
    "operations_manager": "earlydryer_base.group_operations_manager",
    "finance": "earlydryer_base.group_finance",
    "admin": "earlydryer_base.group_admin",
}
# who may do what (section 11 of the specification); branch managers only on
# their own plants (Operations Manager and Finance see every plant)
RIGHTS = {
    "book": ("front_desk", "customer_service", "branch_manager"),
    "plan": ("branch_manager",),
    "close": ("branch_manager", "finance"),
    "config": ("operations_manager",),
    "waive": ("branch_manager",),
    "outcome": ("branch_manager",),
}
# fields only the stop engine (methods) writes
PROTECTED_FIELDS = {
    "state",
    "cod_amount",
    "cash_collected",
    "transfer_amount",
    "collection_method",
    "fee_charged_move_id",
    "fee_line_ref",
    "cod_payment_id",
    "credit_approver_employee_id",
}
FEE_FIELDS = {"fee_amount", "fee_waived", "fee_waive_reason", "failed_fee_amount"}
SNAPSHOT_FIELDS = (
    "address_text",
    "area_id",
    "landmark",
    "gate_instructions",
    "phone",
    "latitude",
    "longitude",
)


class EarlydryerLogisticsStop(models.Model):
    _name = "earlydryer.logistics.stop"
    _description = "Earlydryer Pickup / Delivery Stop"
    _inherit = ["mail.thread", "mail.activity.mixin", "earlydryer.branch.mixin"]
    _order = "slot_start, trip_id, sequence, id"
    _rec_names_search = ["name", "partner_id.name", "phone"]

    name = fields.Char(
        string="Number",
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: self.env._("New"),
    )
    stop_type = fields.Selection(
        STOP_TYPES, required=True, default="pickup", tracking=True, index=True
    )
    state = fields.Selection(
        STATES,
        required=True,
        default="draft",
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
        group_expand=True,
    )
    source = fields.Selection(SOURCES, required=True, default="backend")
    company_id = fields.Many2one(
        related="earlydryer_branch_id.company_id", store=True, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    partner_id = fields.Many2one(
        "res.partner", string="Customer", required=True, tracking=True, index=True
    )
    address_partner_id = fields.Many2one(
        "res.partner",
        string="Address",
        help="Contact whose address is used (the customer or one of their "
        "delivery addresses).",
    )
    # address snapshot, copied when the stop is scheduled
    address_text = fields.Char(string="Street Address")
    area_id = fields.Many2one("earlydryer.area", string="Area", index=True)
    landmark = fields.Char()
    gate_instructions = fields.Char()
    phone = fields.Char()
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    map_url = fields.Char(compute="_compute_map_url")
    zone_id = fields.Many2one("earlydryer.delivery.zone", string="Zone", index=True)
    distance_km = fields.Float(string="Distance (km)", digits=(8, 2))
    quote_message = fields.Char(readonly=True)

    slot_template_id = fields.Many2one(
        "earlydryer.logistics.slot.template", string="Slot", index=True
    )
    slot_date = fields.Date(index=True, tracking=True)
    slot_start = fields.Datetime()
    slot_end = fields.Datetime()
    slot_label = fields.Char(compute="_compute_slot_label")

    job_id = fields.Many2one(
        "laundry.job",
        string="Laundry Job",
        index="btree_not_null",
        tracking=True,
        help="Delivery: the job delivered. Pickup: the job created when the "
        "bags are priced at the plant.",
    )
    job_ids = fields.Many2many(
        "laundry.job",
        "earlydryer_logistics_stop_job_rel",
        "stop_id",
        "job_id",
        string="Jobs",
        help="All jobs of the stop (batched / corporate pickups); the main one "
        "is the Laundry Job.",
    )
    job_state = fields.Selection(related="job_id.state", string="Job Stage")
    order_amount = fields.Monetary(
        help="Order value used by the quote (free-delivery threshold, minimum)."
    )
    express = fields.Boolean(tracking=True)

    fee_amount = fields.Monetary(string="Fee", tracking=True)
    fee_waived = fields.Boolean(tracking=True)
    fee_waive_reason = fields.Char(tracking=True)
    failed_fee_amount = fields.Monetary(
        string="Failed-Attempt Fee",
        tracking=True,
        help="Fee of the previous failed attempt, charged with this stop "
        "(placeholder rule, off by default).",
    )
    fee_charged_move_id = fields.Many2one(
        "account.move", string="Fee Invoice", readonly=True, copy=False
    )
    fee_line_ref = fields.Char(
        string="Fee Order Lines",
        readonly=True,
        copy=False,
        help="sale.order.line or pos.order.line ids carrying the fee.",
    )
    fee_charged = fields.Boolean(compute="_compute_fee_charged")
    fee_total = fields.Monetary(compute="_compute_fee_charged")

    cod_amount = fields.Monetary(
        string="Cash on Delivery",
        readonly=True,
        copy=False,
        tracking=True,
        help="Amount the rider collects at the door.",
    )
    cash_collected = fields.Monetary(readonly=True, copy=False, tracking=True)
    transfer_amount = fields.Monetary(
        string="Transfer Confirmed",
        readonly=True,
        copy=False,
        help="Paid by transfer while the rider waited, confirmed by the office. "
        "Finance matches it with the bank statement.",
    )
    collection_method = fields.Selection(
        COLLECTION_METHODS, readonly=True, copy=False, tracking=True
    )
    cash_short = fields.Monetary(
        compute="_compute_cash_short", store=True, string="Collection Short"
    )
    cod_payment_id = fields.Many2one(
        "account.payment", string="Door Payment", readonly=True, copy=False
    )
    credit_approver_employee_id = fields.Many2one(
        "hr.employee", string="Credit Approved By", readonly=True, copy=False
    )
    transfer_matched = fields.Boolean(
        copy=False,
        help="Finance matched the transfer with the bank statement.",
    )

    trip_id = fields.Many2one(
        "earlydryer.logistics.trip",
        string="Trip",
        index=True,
        tracking=True,
        copy=False,
        group_expand="_read_group_trip_id",
        ondelete="restrict",
    )
    sequence = fields.Integer(default=10, copy=False)
    rider_employee_id = fields.Many2one(
        related="trip_id.rider_employee_id", store=True, string="Rider"
    )
    carrier_partner_id = fields.Many2one(
        related="trip_id.carrier_partner_id", store=True, string="Carrier"
    )
    rider_user_id = fields.Many2one(
        related="trip_id.rider_user_id", store=True, string="Rider User", index=True
    )
    loaded = fields.Boolean(
        string="On Board",
        readonly=True,
        copy=False,
        help="Delivery: the bag label was scanned onto the trip.",
    )
    loaded_on = fields.Datetime(readonly=True, copy=False)
    not_loaded = fields.Boolean(
        compute="_compute_not_loaded",
        help="Trip started but the bag was not scanned.",
    )

    attempt = fields.Integer(default=1, readonly=True, copy=False)
    previous_stop_id = fields.Many2one(
        "earlydryer.logistics.stop", readonly=True, copy=False, index=True
    )
    next_stop_id = fields.Many2one(
        "earlydryer.logistics.stop", readonly=True, copy=False
    )
    fail_reason_id = fields.Many2one(
        "earlydryer.logistics.fail.reason", readonly=True, copy=False, tracking=True
    )
    fail_note = fields.Text(readonly=True, copy=False)
    failed_fee_applied = fields.Boolean(
        readonly=True,
        copy=False,
        help="A failed-attempt fee was put on the next attempt.",
    )

    # proof
    signature = fields.Binary(attachment=True, copy=False)
    recipient_name = fields.Char(copy=False)
    photo_ids = fields.Many2many(
        "ir.attachment",
        "earlydryer_logistics_stop_photo_rel",
        "stop_id",
        "attachment_id",
        string="Photos",
        copy=False,
    )
    photo_count = fields.Integer(compute="_compute_photo_count")
    gps_lat = fields.Float(string="GPS Latitude", digits=(10, 7), copy=False)
    gps_lng = fields.Float(string="GPS Longitude", digits=(10, 7), copy=False)
    gps_accuracy_m = fields.Float(string="GPS Accuracy (m)", copy=False)
    gps_captured_on = fields.Datetime(copy=False)
    gps_low_accuracy = fields.Boolean(
        compute="_compute_gps_low_accuracy", store=True, string="Low GPS Accuracy"
    )
    arrived_on = fields.Datetime(readonly=True, copy=False)
    done_on = fields.Datetime(readonly=True, copy=False, index=True)
    on_slot = fields.Boolean(
        compute="_compute_on_slot",
        store=True,
        help="Done within the slot window.",
    )

    # pickup capture (no pricing at the door)
    bag_count = fields.Integer(copy=False)
    piece_count_estimate = fields.Integer(copy=False)
    pickup_note = fields.Char(copy=False, help="Tamper seal or bag tag numbers.")
    plant_arrival_on = fields.Datetime(
        string="Arrived at Plant",
        copy=False,
        help="When the bags reached the plant: the job's intake time.",
    )
    return_delivery = fields.Boolean(
        help="Pickup: the customer wants the order delivered back."
    )

    customer_note = fields.Text()
    internal_note = fields.Text()
    needs_review = fields.Boolean(
        copy=False,
        tracking=True,
        help="Something recorded on the phone offline needs the office (e.g. a "
        "manager PIN refused when it synced).",
    )
    review_note = fields.Text(copy=False)

    _attempt_positive = models.Constraint(
        "CHECK(attempt >= 1)", "The attempt number starts at 1."
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends("latitude", "longitude", "address_text", "area_id", "landmark")
    def _compute_map_url(self):
        for stop in self:
            stop.map_url = self._earlydryer_map_url(
                stop.latitude,
                stop.longitude,
                ", ".join(
                    filter(
                        None,
                        [stop.address_text, stop.area_id.name, stop.landmark],
                    )
                ),
            )

    @api.model
    def _earlydryer_map_url(self, lat, lng, text):
        if lat or lng:
            query = f"{lat:.6f},{lng:.6f}"
        elif text:
            query = quote_plus(text)
        else:
            return False
        return f"https://www.google.com/maps/search/?api=1&query={query}"

    @api.depends("slot_template_id", "slot_start", "slot_end")
    def _compute_slot_label(self):
        Slot = self.env["earlydryer.logistics.slot.template"]
        for stop in self:
            if not stop.slot_start:
                stop.slot_label = False
                continue
            tz = Slot._earlydryer_tz(stop.earlydryer_branch_id)
            utc = ZoneInfo("UTC")
            start = stop.slot_start.replace(tzinfo=utc).astimezone(tz)
            end = stop.slot_end.replace(tzinfo=utc).astimezone(tz) if stop.slot_end else start
            stop.slot_label = (
                f"{start:%a %d %b} {stop.slot_template_id.name or ''} "
                f"{start:%H:%M}-{end:%H:%M}"
            ).replace("  ", " ")

    @api.depends(
        "fee_charged_move_id", "fee_line_ref", "fee_amount", "fee_waived",
        "failed_fee_amount",
    )
    def _compute_fee_charged(self):
        for stop in self:
            stop.fee_charged = bool(stop.fee_charged_move_id or stop.fee_line_ref)
            stop.fee_total = (
                0.0 if stop.fee_waived else stop.fee_amount
            ) + stop.failed_fee_amount

    @api.depends("cod_amount", "cash_collected", "transfer_amount", "state")
    def _compute_cash_short(self):
        for stop in self:
            short = stop.cod_amount - stop.cash_collected - stop.transfer_amount
            stop.cash_short = (
                max(short, 0.0)
                if stop.state == "done" and stop.stop_type == "delivery"
                else 0.0
            )

    @api.depends("stop_type", "state", "loaded", "trip_id.state")
    def _compute_not_loaded(self):
        for stop in self:
            stop.not_loaded = (
                stop.stop_type == "delivery"
                and stop.state == "assigned"
                and stop.trip_id.state == "in_progress"
                and not stop.loaded
            )

    def _compute_photo_count(self):
        for stop in self:
            stop.photo_count = len(stop.photo_ids)

    @api.depends("gps_accuracy_m", "gps_captured_on")
    def _compute_gps_low_accuracy(self):
        threshold = self._earlydryer_gps_threshold()
        for stop in self:
            stop.gps_low_accuracy = bool(
                stop.gps_captured_on and stop.gps_accuracy_m > threshold
            )

    @api.depends("done_on", "slot_start", "slot_end", "state")
    def _compute_on_slot(self):
        for stop in self:
            stop.on_slot = bool(
                stop.state == "done"
                and stop.done_on
                and stop.slot_start
                and stop.slot_end
                and stop.slot_start <= stop.done_on <= stop.slot_end
            )

    @api.model
    def _earlydryer_gps_threshold(self):
        value = self.env["ir.config_parameter"].sudo().get_param(PARAM_GPS_ACCURACY)
        try:
            return float(value) if value else DEFAULT_GPS_ACCURACY
        except ValueError:
            return DEFAULT_GPS_ACCURACY

    @api.model
    def _read_group_trip_id(self, trips, domain):
        """Planning board: show the open trips of the day(s) shown, even empty."""
        dates = set()
        for leaf in Domain(domain).iter_conditions():
            if leaf.field_expr == "slot_date" and leaf.operator in ("=", "in"):
                value = leaf.value
                dates |= set(value if isinstance(value, (list, tuple)) else [value])
        trip_domain = [("state", "in", ("draft", "planned", "in_progress"))]
        if dates:
            trip_domain.append(("date", "in", list(dates)))
        else:
            trip_domain.append(("date", "=", fields.Date.context_today(self)))
        return trips | trips.search(trip_domain)

    # ------------------------------------------------------------------
    # Rights
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_has_right(self, right, branches=None):
        """Whether the user may do ``right`` (see RIGHTS) on ``branches``."""
        user = self.env.user
        if self.env.su or user.has_group(GROUPS["admin"]):
            return True
        if not any(user.has_group(GROUPS[key]) for key in RIGHTS[right]):
            return False
        if branches:
            allowed = user._earlydryer_allowed_branches()
            if any(branch not in allowed for branch in branches):
                return False
        return True

    @api.model
    def _earlydryer_check_right(self, right, branches=None):
        if not self._earlydryer_has_right(right, branches):
            labels = {
                "book": self.env._("book pickups or arrange deliveries"),
                "plan": self.env._("plan trips"),
                "close": self.env._("close trips and hand over rider cash"),
                "config": self.env._("configure zones, fees and slots"),
                "waive": self.env._("waive or change logistics fees"),
                "outcome": self.env._("record stop outcomes from the office"),
            }
            raise AccessError(
                self.env._(
                    "You are not allowed to %(what)s%(where)s.",
                    what=labels.get(right, right),
                    where=(
                        " " + self.env._("for %s", ", ".join(branches.mapped("display_name")))
                        if branches
                        else ""
                    ),
                )
            )
        return True

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.context.get(STOP_CTX):
            self._earlydryer_check_right("book")
            for vals in vals_list:
                if PROTECTED_FIELDS & set(vals):
                    raise AccessError(
                        self.env._("These stop fields are set by the system.")
                    )
                vals.pop("state", None)
        stops = super().create(vals_list)
        for stop in stops:
            if not stop.name or stop.name == self.env._("New"):
                sequence = stop.earlydryer_branch_id._earlydryer_logistics_ensure_sequences()[
                    "stop"
                ]
                stop.name = sequence.sudo().next_by_id()
            if stop.job_id and stop.job_id not in stop.job_ids:
                stop.job_ids = [Command.link(stop.job_id.id)]
        return stops

    def write(self, vals):
        if not self.env.su and not self.env.context.get(STOP_CTX):
            if PROTECTED_FIELDS & set(vals):
                raise AccessError(
                    self.env._(
                        "Use the stop buttons: state, cash and fee charges are set "
                        "by the system."
                    )
                )
            if FEE_FIELDS & set(vals):
                if any(stop.state != "draft" for stop in self) or vals.get(
                    "fee_waived"
                ):
                    self._earlydryer_check_right(
                        "waive", self.earlydryer_branch_id
                    )
                if vals.get("fee_waived") and not (
                    vals.get("fee_waive_reason")
                    or all(stop.fee_waive_reason for stop in self)
                ):
                    raise UserError(self.env._("Give the reason for waiving the fee."))
                if self.filtered("fee_charged") and (
                    {"fee_amount", "failed_fee_amount"} & set(vals)
                    or vals.get("fee_waived")
                ):
                    raise UserError(
                        self.env._(
                            "The fee is already charged: cancel or credit its "
                            "invoice or order line first."
                        )
                    )
            if "trip_id" in vals or "sequence" in vals:
                self._earlydryer_check_right(
                    "plan",
                    self.earlydryer_branch_id
                    | self.env["earlydryer.logistics.trip"]
                    .browse(vals.get("trip_id") or [])
                    .earlydryer_branch_id,
                )
        if "trip_id" in vals:
            self._earlydryer_check_trip_change(vals["trip_id"])
        old_trips = {stop.id: stop.trip_id for stop in self} if "trip_id" in vals else {}
        res = super().write(vals)
        if "trip_id" in vals:
            self._earlydryer_after_trip_change(old_trips)
        if "job_id" in vals:
            for stop in self.filtered(lambda s: s.job_id and s.job_id not in s.job_ids):
                stop.job_ids = [Command.link(stop.job_id.id)]
        return res

    def unlink(self):
        if not self.env.su and not self.env.user.has_group(GROUPS["admin"]):
            if any(stop.state != "draft" for stop in self):
                raise UserError(
                    self.env._("Only draft stops can be deleted; cancel the others.")
                )
        return super().unlink()

    def _earlydryer_check_trip_change(self, trip_id):
        trip = self.env["earlydryer.logistics.trip"].browse(trip_id or [])
        for stop in self:
            if stop.trip_id == trip:
                continue
            if stop.state not in ("scheduled", "assigned"):
                raise UserError(
                    self.env._(
                        "Stop %(stop)s is %(state)s: only scheduled or assigned "
                        "stops move between trips.",
                        stop=stop.name,
                        state=stop._earlydryer_state_label(),
                    )
                )
            if trip:
                if trip.state in ("done", "cancelled"):
                    raise UserError(
                        self.env._("Trip %(trip)s is closed.", trip=trip.name)
                    )
                if trip.earlydryer_branch_id != stop.earlydryer_branch_id:
                    raise UserError(
                        self.env._(
                            "Stop %(stop)s belongs to another plant than trip "
                            "%(trip)s.",
                            stop=stop.name,
                            trip=trip.name,
                        )
                    )

    def _earlydryer_after_trip_change(self, old_trips):
        engine = self.with_context(**{STOP_CTX: True})
        for stop in engine:
            old = old_trips.get(stop.id)
            if stop.trip_id and stop.state == "scheduled":
                stop.state = "assigned"
                stop._earlydryer_refresh_cod()
            elif not stop.trip_id and stop.state == "assigned":
                stop.write({"state": "scheduled", "loaded": False, "loaded_on": False})
            if old and old != stop.trip_id and stop.loaded:
                stop.write({"loaded": False, "loaded_on": False})

    def _earlydryer_state_label(self):
        self.ensure_one()
        return dict(self._fields["state"]._description_selection(self.env)).get(
            self.state, self.state
        )

    # ------------------------------------------------------------------
    # Address and quote
    # ------------------------------------------------------------------

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        for stop in self:
            if stop.partner_id and (
                not stop.address_partner_id
                or stop.address_partner_id.commercial_partner_id
                != stop.partner_id.commercial_partner_id
            ):
                stop.address_partner_id = stop.partner_id

    def _earlydryer_address(self):
        self.ensure_one()
        return self.address_partner_id or self.partner_id

    def _earlydryer_snapshot_address(self):
        """Copy the address so later edits of the contact keep history."""
        for stop in self:
            address = stop._earlydryer_address().sudo()
            street = ", ".join(
                filter(None, [address.street, address.street2, address.city])
            )
            stop.with_context(**{STOP_CTX: True}).write(
                {
                    "address_text": street or False,
                    "area_id": address.earlydryer_area_id.id,
                    "landmark": address.earlydryer_landmark,
                    "gate_instructions": address.earlydryer_gate_instructions,
                    "phone": address.phone or stop.partner_id.phone,
                    "latitude": address.partner_latitude,
                    "longitude": address.partner_longitude,
                }
            )

    def _earlydryer_quote(self, date=None, days=7):
        self.ensure_one()
        return self.env["earlydryer.logistics.quote"].quote(
            self.partner_id,
            self._earlydryer_address(),
            self.earlydryer_branch_id,
            self.stop_type,
            date or self.slot_date or fields.Date.context_today(self),
            express=self.express,
            order_amount=self.order_amount or self._earlydryer_order_amount(),
            days=days,
        )

    def _earlydryer_order_amount(self):
        self.ensure_one()
        job = self.job_id.sudo()
        return job.amount_total if job else 0.0

    def _earlydryer_set_slot(self, key):
        """Put the stop on a concrete slot (``"YYYY-MM-DD|template_id"``)."""
        Slot = self.env["earlydryer.logistics.slot.template"]
        for stop in self:
            template, day = Slot._earlydryer_parse_key(key)
            if not template or template.earlydryer_branch_id != stop.earlydryer_branch_id:
                raise UserError(self.env._("Choose an available slot of the plant."))
            available = Slot.available_slots(
                stop.earlydryer_branch_id,
                stop.stop_type,
                day,
                day,
                zone=stop.zone_id or None,
            )
            if key not in [slot["key"] for slot in available]:
                raise UserError(
                    self.env._(
                        "Slot %(slot)s is full, past its cut-off or a holiday.",
                        slot=template.display_name,
                    )
                )
            start, end = template._earlydryer_bounds(day)
            stop.with_context(**{STOP_CTX: True}).write(
                {
                    "slot_template_id": template.id,
                    "slot_date": day,
                    "slot_start": start,
                    "slot_end": end,
                }
            )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def action_schedule(self):
        """Draft → Scheduled: snapshot the address, charge the fee, set the
        cash to collect and tell the customer."""
        self._earlydryer_check_right("book", self.earlydryer_branch_id)
        for stop in self:
            if stop.state != "draft":
                raise UserError(
                    self.env._("Stop %(stop)s is already scheduled.", stop=stop.name)
                )
            if not stop.slot_start:
                raise UserError(
                    self.env._("Choose a slot for stop %(stop)s.", stop=stop.name)
                )
            if stop.stop_type == "delivery":
                if not stop.job_id:
                    raise UserError(
                        self.env._("Delivery %(stop)s has no job.", stop=stop.name)
                    )
                if stop.job_id.state in ("delivered", "collected", "cancelled"):
                    raise UserError(
                        self.env._(
                            "Job %(job)s is closed: nothing to deliver.",
                            job=stop.job_id.name,
                        )
                    )
                other = self.search(
                    [
                        ("id", "!=", stop.id),
                        ("stop_type", "=", "delivery"),
                        ("job_id", "=", stop.job_id.id),
                        ("state", "in", ("scheduled",) + ACTIVE_STATES),
                    ],
                    limit=1,
                )
                if other:
                    raise UserError(
                        self.env._(
                            "Job %(job)s is already on delivery %(stop)s.",
                            job=stop.job_id.name,
                            stop=other.name,
                        )
                    )
            stop._earlydryer_snapshot_address()
            stop.with_context(**{STOP_CTX: True}).state = "scheduled"
            self._earlydryer_charge_fee(stop)
            stop._earlydryer_refresh_cod()
            stop._earlydryer_notify_scheduled()
        return True

    def _earlydryer_notify_scheduled(self):
        self.ensure_one()
        Notify = self.env["earlydryer.notify.message"]
        context = {
            "occurrence": f"scheduled:{self.id}",
            "slot": self.slot_label or "",
            "fee": self._earlydryer_format(self.fee_total),
            "cod": self._earlydryer_format(self.cod_amount),
        }
        if self.stop_type == "pickup":
            context["summary"] = self.env._(
                "%(slot)s, fee %(fee)s", slot=context["slot"], fee=context["fee"]
            )
            Notify.notify("pickup_booked", self, context=context)
        else:
            context["number"] = self.job_id.name or self.name
            Notify.notify("delivery_scheduled", self, context=context)

    def _earlydryer_format(self, amount):
        currency = self.currency_id or self.env.company.currency_id
        return f"{currency.symbol or ''}{amount or 0.0:,.2f}"

    def action_cancel(self):
        self._earlydryer_check_right("book", self.earlydryer_branch_id)
        for stop in self:
            if stop.state in ("en_route", "arrived", "done", "failed"):
                raise UserError(
                    self.env._(
                        "Stop %(stop)s is under way or closed: record its outcome "
                        "instead.",
                        stop=stop.name,
                    )
                )
            if stop.fee_charged_move_id and stop.fee_charged_move_id.state == "posted":
                stop.message_post(
                    body=self.env._(
                        "Stop cancelled: fee invoice %(invoice)s stays posted; "
                        "Finance credits it if needed.",
                        invoice=stop.fee_charged_move_id.name,
                    ),
                    subtype_xmlid="mail.mt_note",
                )
            stop.with_context(**{STOP_CTX: True}).write(
                {"state": "cancelled", "trip_id": False, "cod_amount": 0.0}
            )
        return True

    def action_reset_draft(self):
        self._earlydryer_check_right("book", self.earlydryer_branch_id)
        for stop in self:
            if stop.state != "cancelled":
                raise UserError(self.env._("Only cancelled stops go back to draft."))
            stop.with_context(**{STOP_CTX: True}).state = "draft"
        return True

    # ------------------------------------------------------------------
    # Fees
    # ------------------------------------------------------------------

    def _earlydryer_fee_products(self):
        return (
            self.env.ref("earlydryer_logistics.product_delivery_fee"),
            self.env.ref("earlydryer_logistics.product_failed_delivery_fee"),
        )

    def _earlydryer_fee_lines(self):
        """``[(product, amount, label)]`` still to charge on this stop."""
        self.ensure_one()
        if self.fee_charged:
            return []
        fee_product, failed_product = self._earlydryer_fee_products()
        lines = []
        currency = self.currency_id or self.env.company.currency_id
        if not self.fee_waived and currency.compare_amounts(self.fee_amount, 0.0) > 0:
            label = (
                self.env._("Pickup fee %(stop)s", stop=self.name)
                if self.stop_type == "pickup"
                else self.env._("Delivery fee %(stop)s", stop=self.name)
            )
            if self.express:
                label += " (" + self.env._("express") + ")"
            lines.append((fee_product.sudo(), self.fee_amount, label))
        if currency.compare_amounts(self.failed_fee_amount, 0.0) > 0:
            lines.append(
                (
                    failed_product.sudo(),
                    self.failed_fee_amount,
                    self.env._(
                        "Failed delivery fee (attempt %(attempt)s of %(prev)s)",
                        attempt=self.attempt - 1,
                        prev=self.previous_stop_id.name or "",
                    ),
                )
            )
        return lines

    @api.model
    def _earlydryer_charge_fee(self, stop):
        """Charge the fee(s) of ``stop`` once.

        * the job's sales order is still open and not fully invoiced: add the
          fee lines to it (included in the job's total);
        * otherwise (invoiced order, POS job, manual job): a small posted
          customer invoice linked to the job and the stop;
        * pickups without job: nothing yet, the fee is added when the bags are
          priced at the plant (POS line or backend order);
        * fee waived or zero: nothing.

        earlydryer_corporate overrides this (contracts with free delivery).
        """
        stop.ensure_one()
        lines = stop._earlydryer_fee_lines()
        job = stop.job_id.sudo()
        if not lines or not job:
            return self.env["account.move"]
        engine = stop.with_context(**{STOP_CTX: True})
        order = job.sale_order_id
        if (
            order
            and order.state in ("draft", "sent", "sale")
            and not order.locked
            and order.invoice_status != "invoiced"
        ):
            order_lines = self.env["sale.order.line"].sudo().create(
                [
                    {
                        "order_id": order.id,
                        "product_id": product.id,
                        "name": label,
                        "product_uom_qty": 1,
                        "price_unit": amount,
                    }
                    for product, amount, label in lines
                ]
            )
            engine.fee_line_ref = "sale.order.line," + ",".join(
                str(line_id) for line_id in order_lines.ids
            )
            stop.message_post(
                body=self.env._(
                    "Fee added to sales order %(order)s.", order=order.name
                ),
                subtype_xmlid="mail.mt_note",
            )
            return self.env["account.move"]
        invoice = (
            self.env["account.move"]
            .sudo()
            .with_context(earlydryer_move_branch_id=stop.earlydryer_branch_id.id)
            .create(
                {
                    "move_type": "out_invoice",
                    "partner_id": job.partner_id.id,
                    "invoice_date": fields.Date.context_today(self),
                    "earlydryer_branch_id": stop.earlydryer_branch_id.id,
                    "earlydryer_logistics_stop_id": stop.id,
                    "earlydryer_logistics_job_id": job.id,
                    "invoice_origin": f"{job.name} / {stop.name}",
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": product.id,
                                "name": label,
                                "quantity": 1,
                                "price_unit": amount,
                            }
                        )
                        for product, amount, label in lines
                    ],
                }
            )
        )
        invoice.action_post()
        engine.fee_charged_move_id = invoice
        stop.message_post(
            body=self.env._("Fee invoice %(invoice)s posted.", invoice=invoice.name),
            subtype_xmlid="mail.mt_note",
        )
        return invoice

    def action_charge_fee(self):
        """Charge a fee changed after scheduling (manager)."""
        self._earlydryer_check_right("waive", self.earlydryer_branch_id)
        for stop in self:
            if stop.state in ("draft", "cancelled"):
                continue
            self._earlydryer_charge_fee(stop)
            stop._earlydryer_refresh_cod()
        return True

    # ------------------------------------------------------------------
    # Cash on delivery
    # ------------------------------------------------------------------

    def _earlydryer_cod_allowed(self):
        self.ensure_one()
        branch = self.earlydryer_branch_id.sudo()
        partner = self.partner_id.sudo().commercial_partner_id
        return bool(
            self.stop_type == "delivery"
            and branch.earlydryer_allow_cod
            and not partner.earlydryer_cod_blocked
            and not self.partner_id.sudo().earlydryer_cod_blocked
        )

    def _earlydryer_refresh_cod(self):
        """COD = what the job still owes (fee included), when COD is allowed."""
        for stop in self.filtered(
            lambda s: s.stop_type == "delivery"
            and s.state in ("scheduled",) + ACTIVE_STATES
            and s.job_id
        ):
            job = stop.job_id.sudo()
            job.invalidate_recordset(["amount_due", "amount_total", "amount_paid"])
            due = job.amount_due if stop._earlydryer_cod_allowed() else 0.0
            if stop.currency_id.compare_amounts(due, stop.cod_amount):
                stop.with_context(**{STOP_CTX: True}).cod_amount = max(due, 0.0)

    # ------------------------------------------------------------------
    # At the door
    # ------------------------------------------------------------------

    def _earlydryer_record_gps(self, gps):
        """``gps``: ``{"lat", "lng", "accuracy", "at"}`` (any may be missing)."""
        self.ensure_one()
        if not gps or gps.get("lat") in (None, False) or gps.get("lng") in (None, False):
            return False
        vals = {
            "gps_lat": float(gps["lat"]),
            "gps_lng": float(gps["lng"]),
            "gps_accuracy_m": float(gps.get("accuracy") or 0.0),
            "gps_captured_on": fields.Datetime.to_datetime(gps.get("at"))
            or fields.Datetime.now(),
        }
        self.with_context(**{STOP_CTX: True}).write(vals)
        return True

    def _earlydryer_save_customer_location(self, force=False):
        """Store the GPS of the stop on the address when it has none (or the
        rider confirmed a correction)."""
        self.ensure_one()
        address = self._earlydryer_address().sudo()
        if not self.gps_captured_on:
            return False
        if (address.partner_latitude or address.partner_longitude) and not force:
            return False
        address.write(
            {
                "partner_latitude": self.gps_lat,
                "partner_longitude": self.gps_lng,
                "earlydryer_gps_accuracy_m": self.gps_accuracy_m,
                "earlydryer_gps_captured_on": self.gps_captured_on,
            }
        )
        self.message_post(
            body=self.env._(
                "Location saved for %(partner)s (accuracy %(accuracy).0f m).",
                partner=address.display_name,
                accuracy=self.gps_accuracy_m,
            ),
            subtype_xmlid="mail.mt_note",
        )
        return True

    def _earlydryer_check_open(self, states):
        for stop in self:
            if stop.state not in states:
                raise UserError(
                    self.env._(
                        "Stop %(stop)s is %(state)s.",
                        stop=stop.name,
                        state=stop._earlydryer_state_label(),
                    )
                )

    def _earlydryer_arrive(self, gps=None, at=None):
        self.ensure_one()
        if self.state == "arrived":
            return True
        self._earlydryer_check_open(("assigned", "en_route"))
        if self.stop_type == "delivery" and not self.loaded and self.state == "assigned":
            raise UserError(
                self.env._(
                    "Scan the bag of %(job)s onto the trip before the delivery.",
                    job=self.job_id.name,
                )
            )
        self.with_context(**{STOP_CTX: True}).write(
            {
                "state": "arrived",
                "arrived_on": fields.Datetime.to_datetime(at) or fields.Datetime.now(),
            }
        )
        self._earlydryer_record_gps(gps)
        return True

    def _earlydryer_rider_employee(self):
        self.ensure_one()
        return self.trip_id.rider_employee_id.sudo()

    def _earlydryer_verify_pin(self, employee, pin):
        """Employee whose PIN ``pin`` matches and who may approve credit on
        the job (credit rule's approver group, else a Branch Manager)."""
        self.ensure_one()
        employee = employee.sudo()
        if not employee or not pin or not employee.pin or employee.pin != str(pin):
            return False
        user = employee.user_id
        if not user or not user.active:
            return False
        job = self.job_id.sudo()
        short = self._earlydryer_short_amount()
        rule = job._earlydryer_approval_rule("credit", short) if short > 0 else False
        if rule:
            return rule.sudo().approver_group_id in user.all_group_ids
        return user.has_group(GROUPS["branch_manager"])

    def _earlydryer_short_amount(self, collected=None, transfer=None):
        self.ensure_one()
        collected = self.cash_collected if collected is None else collected
        transfer = self.transfer_amount if transfer is None else transfer
        currency = self.currency_id or self.env.company.currency_id
        return currency.round(max(self.cod_amount - collected - transfer, 0.0))

    def _earlydryer_log_door_credit(self, employee, short):
        """Approved credit request on the job for a short collection approved
        with a manager PIN at the door."""
        self.ensure_one()
        job = self.job_id.sudo()
        user = employee.sudo().user_id
        rule = job._earlydryer_approval_rule("credit", short)
        request = self.env["earlydryer.approval.request"]
        if rule and not job._earlydryer_credit_approved(short):
            request = (
                request.sudo()
                .with_context(**{INTERNAL_CTX: True})
                .create(
                    {
                        "rule_id": rule.id,
                        "res_model": job._name,
                        "res_id": job.id,
                        "earlydryer_branch_id": job.earlydryer_branch_id.id,
                        "company_id": job.company_id.id,
                        "value": short,
                        "reason": self.env._(
                            "Credit approved at the door on %(stop)s by %(employee)s "
                            "(PIN).",
                            stop=self.name,
                            employee=employee.name,
                        ),
                        "state": "approved",
                        "requested_by_id": self.env.user.id,
                        "decided_by_id": user.id,
                        "decided_on": fields.Datetime.now(),
                    }
                )
            )
        job.message_post(
            body=self.env._(
                "%(amount)s left on credit at the door (%(stop)s), approved by "
                "%(employee)s with their PIN.",
                amount=self._earlydryer_format(short),
                stop=self.name,
                employee=employee.name,
            ),
            subtype_xmlid="mail.mt_note",
        )
        return request

    def _earlydryer_complete(self, vals):
        """Done at the door (rider view, or the office for a 3PL / phone).

        ``vals`` keys: ``recipient_name``, ``signature`` (base64),
        ``cash_collected``, ``collection_method``, ``transfer_amount``,
        ``approver_employee_id`` + ``pin`` (short collection), ``offline``
        (the PIN could not be checked when the action was taken),
        ``bag_count``, ``piece_count_estimate``, ``pickup_note``, ``gps``,
        ``done_on``, ``save_location``, ``fix_location``.
        """
        self.ensure_one()
        if self.state == "done":
            return True
        self._earlydryer_check_open(("assigned", "en_route", "arrived"))
        engine = self.with_context(**{STOP_CTX: True})
        done_on = fields.Datetime.to_datetime(vals.get("done_on")) or fields.Datetime.now()
        self._earlydryer_record_gps(vals.get("gps"))
        common = {
            "recipient_name": vals.get("recipient_name") or self.recipient_name,
            "done_on": done_on,
            "arrived_on": self.arrived_on or done_on,
        }
        if vals.get("signature"):
            common["signature"] = vals["signature"]
        if self.stop_type == "pickup":
            bags = int(vals.get("bag_count") or 0)
            if bags <= 0:
                raise UserError(self.env._("Count the bags picked up."))
            engine.write(
                {
                    **common,
                    "state": "done",
                    "bag_count": bags,
                    "piece_count_estimate": int(vals.get("piece_count_estimate") or 0),
                    "pickup_note": vals.get("pickup_note") or self.pickup_note,
                }
            )
            self._earlydryer_after_location(vals)
            self.env["earlydryer.notify.message"].notify(
                "pickup_done",
                self,
                context={
                    "occurrence": f"done:{self.id}",
                    "summary": self.env._(
                        "%(bags)s bag(s) collected; we will send the price once "
                        "counted at the plant",
                        bags=bags,
                    ),
                },
            )
            return True
        return self._earlydryer_complete_delivery(vals, common)

    def _earlydryer_complete_delivery(self, vals, common):
        self.ensure_one()
        engine = self.with_context(**{STOP_CTX: True})
        job = self.job_id.sudo()
        if job.state != "out_for_delivery":
            raise UserError(
                self.env._(
                    "Job %(job)s is not out for delivery (%(state)s).",
                    job=job.name,
                    state=job._earlydryer_state_label(job.state),
                )
            )
        currency = self.currency_id or self.env.company.currency_id
        method = vals.get("collection_method") or "none"
        collected = currency.round(float(vals.get("cash_collected") or 0.0))
        transfer = currency.round(float(vals.get("transfer_amount") or 0.0))
        if method == "transfer_confirmed" and not transfer:
            transfer = self._earlydryer_short_amount(collected, 0.0)
        if method != "cash" and collected:
            raise UserError(self.env._("Cash collected needs the Cash method."))
        if collected < 0 or transfer < 0:
            raise UserError(self.env._("Amounts collected cannot be negative."))
        short = self._earlydryer_short_amount(collected, transfer)
        approver = self.env["hr.employee"]
        flag_review = False
        if currency.compare_amounts(short, 0.0) > 0:
            employee = self.env["hr.employee"].sudo().browse(
                vals.get("approver_employee_id") or []
            ).exists()
            if employee and self._earlydryer_verify_pin(employee, vals.get("pin")):
                approver = employee
            elif job._earlydryer_credit_approved(short) or vals.get("office_approved"):
                pass  # approved by phone and recorded by the office
            elif employee and vals.get("offline"):
                # handed over offline with a PIN the phone could not check:
                # what happened at the door is never reversed
                flag_review = True
            else:
                raise UserError(
                    self.env._(
                        "%(short)s is still due on %(job)s. Get a manager's PIN or "
                        "an approval by phone recorded by the office, or fail the "
                        "stop with reason \"Unable to pay\" and bring the "
                        "garments back.",
                        short=self._earlydryer_format(short),
                        job=job.name,
                    )
                )
        engine.write(
            {
                **common,
                "state": "done",
                "cash_collected": collected,
                "transfer_amount": transfer,
                "collection_method": method,
                "credit_approver_employee_id": approver.id,
                "needs_review": flag_review or self.needs_review,
                "review_note": (
                    self.env._(
                        "Short collection of %(short)s handed over offline with a "
                        "PIN that was not accepted: check with the rider and the "
                        "manager.",
                        short=self._earlydryer_format(short),
                    )
                    if flag_review
                    else self.review_note
                ),
            }
        )
        if approver:
            self._earlydryer_log_door_credit(approver, short)
        if currency.compare_amounts(collected, 0.0) > 0:
            self._earlydryer_record_cod_payment()
        job.action_move_to(
            "delivered",
            employee=self._earlydryer_rider_employee(),
            note=self.env._("Delivered by %(stop)s", stop=self.name),
        )
        self._earlydryer_after_location(vals)
        if currency.compare_amounts(short, 0.0) > 0:
            self.env["earlydryer.notify.message"].notify(
                "alert_rider_cash_short",
                self,
                context={
                    "value": short,
                    "occurrence": f"short:{self.id}",
                    "summary": self.env._(
                        "%(stop)s (%(job)s): collected %(collected)s of %(cod)s",
                        stop=self.name,
                        job=job.name,
                        collected=self._earlydryer_format(collected + transfer),
                        cod=self._earlydryer_format(self.cod_amount),
                    ),
                },
            )
        if flag_review:
            for user in self._earlydryer_manager_users():
                self.sudo().activity_schedule(
                    TODO_ACTIVITY,
                    summary=self.env._("Check short collection on %(stop)s", stop=self.name),
                    note=self.review_note,
                    user_id=user.id,
                )
        return True

    def _earlydryer_after_location(self, vals):
        if vals.get("save_location") or vals.get("fix_location"):
            self._earlydryer_save_customer_location(force=bool(vals.get("fix_location")))

    def _earlydryer_manager_users(self):
        """Branch managers of the stop's plant (fallback: its manager)."""
        self.ensure_one()
        branch = self.earlydryer_branch_id.sudo()
        group = self.env.ref(GROUPS["branch_manager"])
        users = branch.user_ids.filtered(lambda u: group in u.all_group_ids)
        return users or branch.manager_id

    # ------------------------------------------------------------------
    # Door payments
    # ------------------------------------------------------------------

    def _earlydryer_receivable_debits(self, account):
        """Open receivable debits of the job of this stop on ``account``: its
        invoices (sales flow), its POS receivable and its fee invoices."""
        self.ensure_one()
        job = self.job_id.sudo()
        moves = job.sale_order_id.invoice_ids.filtered(
            lambda m: m.state == "posted" and m.move_type == "out_invoice"
        ) | job._earlydryer_fee_invoices()
        lines = moves.line_ids
        if job.pos_order_id:
            lines |= job.pos_order_id._earlydryer_receivable_lines()
        return lines.filtered(
            lambda line: line.account_id == account
            and not line.reconciled
            and line.balance > 0
        ).sorted(lambda line: (line.date, line.id))

    def _earlydryer_invoice_sale_order(self):
        """Invoice what the job's sales order still has to invoice, so the
        door payment can be matched (invoice policy: on order)."""
        self.ensure_one()
        order = self.job_id.sudo().sale_order_id
        if not order or order.invoice_status != "to invoice":
            return self.env["account.move"]
        try:
            with self.env.cr.savepoint():
                invoices = order.with_context(
                    earlydryer_move_branch_id=self.earlydryer_branch_id.id
                )._create_invoices()
                invoices.action_post()
        except UserError as error:
            _logger.info("Door payment of %s left unmatched: %s", self.name, error)
            return self.env["account.move"]
        return invoices

    def _earlydryer_record_cod_payment(self):
        """Customer payment in the plant's rider cash journal for the cash
        collected, matched with the job's open receivable."""
        self.ensure_one()
        if self.cod_payment_id:
            return self.cod_payment_id
        branch = self.earlydryer_branch_id.sudo()
        journal = branch.earlydryer_rider_journal_id
        if not journal or not journal.default_account_id:
            raise UserError(
                self.env._(
                    "Plant %(branch)s has no rider cash journal: run the "
                    "accounting setup.",
                    branch=branch.display_name,
                )
            )
        job = self.job_id.sudo()
        partner = job.partner_id.commercial_partner_id
        method_line = journal.inbound_payment_method_line_ids[:1]
        payment = (
            self.env["account.payment"]
            .sudo()
            .with_company(branch.company_id)
            .with_context(earlydryer_move_branch_id=branch.id)
            .create(
                {
                    "payment_type": "inbound",
                    "partner_type": "customer",
                    "partner_id": partner.id,
                    "amount": self.cash_collected,
                    "currency_id": (self.currency_id or branch.company_id.currency_id).id,
                    "journal_id": journal.id,
                    "payment_method_line_id": method_line.id,
                    # cash: straight to the rider cash account (cleared by the
                    # handover), no outstanding receipts account
                    "force_outstanding_account_id": journal.default_account_id.id,
                    "date": fields.Date.context_today(self, self.done_on),
                    "memo": self.env._(
                        "Cash on delivery %(stop)s / %(job)s",
                        stop=self.name,
                        job=job.name,
                    ),
                    "earlydryer_logistics_stop_id": self.id,
                }
            )
        )
        payment.action_post()
        self.with_context(**{STOP_CTX: True}).cod_payment_id = payment
        self._earlydryer_reconcile_cod_payment()
        return payment

    def _earlydryer_cod_credit_lines(self):
        self.ensure_one()
        return self.cod_payment_id.sudo().move_id.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
            and line.credit > 0
        )

    def _earlydryer_reconcile_cod_payment(self):
        """Match the door payment with the job's open receivable (also called
        when the POS session of the job closes)."""
        for stop in self.filtered("cod_payment_id"):
            credit = stop._earlydryer_cod_credit_lines().filtered(
                lambda line: not line.reconciled
            )
            if not credit:
                continue
            debits = stop._earlydryer_receivable_debits(credit.account_id)
            if not debits:
                stop._earlydryer_invoice_sale_order()
                debits = stop._earlydryer_receivable_debits(credit.account_id)
            if debits:
                (credit | debits).reconcile()
        return True

    # ------------------------------------------------------------------
    # Failure and next attempt
    # ------------------------------------------------------------------

    def _earlydryer_fail(self, reason, note=None, gps=None, at=None):
        self.ensure_one()
        if self.state == "failed":
            return True
        self._earlydryer_check_open(("assigned", "en_route", "arrived"))
        if not reason:
            raise UserError(self.env._("Give the reason of the failed stop."))
        if reason.note_required and not (note or "").strip():
            raise UserError(
                self.env._("Reason %(reason)s needs a note.", reason=reason.name)
            )
        self._earlydryer_record_gps(gps)
        self.with_context(**{STOP_CTX: True}).write(
            {
                "state": "failed",
                "fail_reason_id": reason.id,
                "fail_note": note or False,
                "done_on": fields.Datetime.to_datetime(at) or fields.Datetime.now(),
                "arrived_on": self.arrived_on
                or fields.Datetime.to_datetime(at)
                or fields.Datetime.now(),
            }
        )
        job = self.job_id.sudo()
        if self.stop_type == "delivery" and job.state == "out_for_delivery":
            job.with_context(**{FAILED_CTX: True}).action_move_to(
                "ready",
                employee=self._earlydryer_rider_employee(),
                note=self.env._(
                    "Delivery %(stop)s failed: %(reason)s. Garments back at the plant.",
                    stop=self.name,
                    reason=reason.name,
                ),
            )
        summary = self.env._(
            "%(stop)s %(customer)s: %(reason)s%(note)s",
            stop=self.name,
            customer=self.partner_id.name,
            reason=reason.name,
            note=f" ({note})" if note else "",
        )
        Notify = self.env["earlydryer.notify.message"]
        if self.stop_type == "delivery":
            Notify.notify(
                "delivery_failed",
                self,
                context={
                    "occurrence": f"failed:{self.id}",
                    "number": job.name or self.name,
                    "summary": reason.name,
                },
            )
        Notify.notify(
            "alert_failed_delivery",
            self,
            context={"occurrence": f"failed:{self.id}", "summary": summary},
        )
        return True

    def _earlydryer_failed_fee(self, reason):
        """Fee of a failed attempt for the next one (placeholder rule)."""
        self.ensure_one()
        branch = self.earlydryer_branch_id.sudo()
        if not reason.fee_applies or self.stop_type != "delivery":
            return 0.0
        if branch.earlydryer_failed_fee_mode == "flat":
            return branch.earlydryer_failed_fee_amount
        if branch.earlydryer_failed_fee_mode == "same_as_delivery":
            return self.fee_amount
        return 0.0

    def action_reschedule(self):
        """New attempt of a failed stop (draft, same address), with the
        failed-attempt fee when the plant's rule applies."""
        self._earlydryer_check_right("book", self.earlydryer_branch_id)
        new_stops = self.browse()
        for stop in self:
            if stop.state != "failed":
                raise UserError(
                    self.env._("Only failed stops are rescheduled.")
                )
            if stop.next_stop_id:
                new_stops |= stop.next_stop_id
                continue
            failed_fee = stop._earlydryer_failed_fee(stop.fail_reason_id)
            new = stop.with_context(**{STOP_CTX: True}).copy(
                {
                    "attempt": stop.attempt + 1,
                    "previous_stop_id": stop.id,
                    "failed_fee_amount": failed_fee,
                    # the delivery fee was charged with the first attempt
                    "fee_amount": 0.0 if stop.fee_charged else stop.fee_amount,
                    "slot_template_id": False,
                    "slot_date": False,
                    "slot_start": False,
                    "slot_end": False,
                    "job_ids": [Command.set(stop.job_ids.ids)],
                }
            )
            stop.with_context(**{STOP_CTX: True}).write(
                {"next_stop_id": new.id, "failed_fee_applied": bool(failed_fee)}
            )
            new_stops |= new
        if len(new_stops) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": self._name,
                "res_id": new_stops.id,
                "view_mode": "form",
                "target": "current",
            }
        return True

    # ------------------------------------------------------------------
    # Pickups at the plant
    # ------------------------------------------------------------------

    def _earlydryer_check_pickup_to_price(self):
        self.ensure_one()
        if self.stop_type != "pickup" or self.state != "done":
            raise UserError(self.env._("Only completed pickups are priced."))
        if self.job_id:
            raise UserError(
                self.env._(
                    "Pickup %(stop)s already has job %(job)s.",
                    stop=self.name,
                    job=self.job_id.name,
                )
            )

    def _earlydryer_mark_at_plant(self):
        for stop in self.filtered(lambda s: not s.plant_arrival_on):
            stop.with_context(**{STOP_CTX: True}).plant_arrival_on = fields.Datetime.now()

    def action_price_backend(self):
        """Create the quotation of the pickup (channel pickup): confirming it
        creates the job through the normal flow."""
        self.ensure_one()
        self._earlydryer_check_right("book", self.earlydryer_branch_id)
        self._earlydryer_check_pickup_to_price()
        self._earlydryer_mark_at_plant()
        order = self.env["sale.order"].search(
            [("earlydryer_pickup_stop_id", "=", self.id), ("state", "!=", "cancel")],
            limit=1,
        )
        if not order:
            fee_lines = self._earlydryer_fee_lines()
            order = self.env["sale.order"].create(
                {
                    "partner_id": self.partner_id.id,
                    "partner_shipping_id": self._earlydryer_address().id,
                    "earlydryer_branch_id": self.earlydryer_branch_id.id,
                    "earlydryer_channel": "pickup",
                    "earlydryer_fulfilment": "deliver" if self.return_delivery else "collect",
                    "earlydryer_express": self.express,
                    "earlydryer_pickup_stop_id": self.id,
                    "note": self.customer_note or False,
                    "order_line": [
                        Command.create(
                            {
                                "product_id": product.id,
                                "name": label,
                                "product_uom_qty": 1,
                                "price_unit": amount,
                            }
                        )
                        for product, amount, label in fee_lines
                    ],
                }
            )
            if fee_lines:
                self.with_context(**{STOP_CTX: True}).fee_line_ref = (
                    "sale.order.line,"
                    + ",".join(str(i) for i in order.order_line.ids)
                )
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": order.id,
            "view_mode": "form",
            "target": "current",
        }

    def _earlydryer_pos_configs(self):
        self.ensure_one()
        return self.env["pos.config"].search(
            [
                ("earlydryer_branch_id", "=", self.earlydryer_branch_id.id),
                ("earlydryer_enabled", "=", True),
            ]
        )

    def action_price_pos(self):
        """Open the plant's till with the customer and the pickup preselected."""
        self.ensure_one()
        self._earlydryer_check_right("book", self.earlydryer_branch_id)
        self._earlydryer_check_pickup_to_price()
        configs = self._earlydryer_pos_configs()
        config = configs.filtered("current_session_id")[:1] or configs[:1]
        if not config:
            raise UserError(
                self.env._(
                    "Plant %(branch)s has no laundry counter.",
                    branch=self.earlydryer_branch_id.display_name,
                )
            )
        if not config.current_session_id:
            raise UserError(
                self.env._(
                    "Open a session on %(pos)s first, then price the pickup.",
                    pos=config.name,
                )
            )
        self._earlydryer_mark_at_plant()
        return {
            "type": "ir.actions.act_url",
            "url": f"/pos/ui/{config.id}?earlydryer_pickup_stop={self.id}",
            "target": "self",
        }

    @api.model
    def earlydryer_pos_pickup_info(self, stop_id, config_id):
        """What the till needs to start the intake of a pickup (POS patch)."""
        stop = self.browse(int(stop_id)).exists()
        config = self.env["pos.config"].browse(int(config_id)).exists()
        if not stop or not config:
            return {"ok": False, "message": self.env._("Pickup not found.")}
        stop.check_access("read")
        if stop.stop_type != "pickup" or stop.state != "done" or stop.job_id:
            return {
                "ok": False,
                "message": self.env._(
                    "Pickup %(stop)s is not waiting to be priced.", stop=stop.name
                ),
            }
        if config.earlydryer_branch_id != stop.earlydryer_branch_id:
            return {
                "ok": False,
                "message": self.env._("Pickup %(stop)s is for another plant.", stop=stop.name),
            }
        fee_product, failed_product = stop._earlydryer_fee_products()
        return {
            "ok": True,
            "stop_id": stop.id,
            "stop_name": stop.name,
            "partner_id": stop.partner_id.id,
            "fulfilment": "deliver" if stop.return_delivery else "collect",
            "express": stop.express,
            "bag_count": stop.bag_count,
            "customer_note": stop.customer_note or "",
            "fee_lines": [
                {"product_id": product.product_variant_id.id
                 if product._name == "product.template" else product.id,
                 "amount": amount, "label": label}
                for product, amount, label in stop._earlydryer_fee_lines()
            ],
            "fee_product_ids": [fee_product.id, failed_product.id],
        }

    def _earlydryer_link_job(self, job, source=None):
        """Called when the job of a priced pickup is created."""
        self.ensure_one()
        vals = {"job_id": job.id, "job_ids": [Command.link(job.id)]}
        if source is not None and source._name == "pos.order" and not self.fee_line_ref:
            fee_products = self.env["product.product"].browse(
                [p.id for p in self._earlydryer_fee_products()]
            )
            fee_lines = source.lines.filtered(lambda line: line.product_id in fee_products)
            if fee_lines:
                vals["fee_line_ref"] = "pos.order.line," + ",".join(
                    str(i) for i in fee_lines.ids
                )
        self.with_context(**{STOP_CTX: True}).write(vals)
        self.message_post(
            body=Markup(self.env._("Priced into job %(job)s.", job=job.name)),
            subtype_xmlid="mail.mt_note",
        )
        if self.return_delivery and job.fulfilment != "deliver":
            job.sudo().fulfilment = "deliver"
        return True

    def _earlydryer_return_address(self):
        """Address of the return delivery: the pickup's."""
        self.ensure_one()
        return self._earlydryer_address()

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def action_open_schedule_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Schedule %s", self.name),
            "res_model": "earlydryer.logistics.schedule.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_stop_id": self.id},
        }

    def action_open_outcome_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Record Outcome"),
            "res_model": "earlydryer.logistics.outcome.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_stop_id": self.id},
        }

    def action_view_photos(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Photos"),
            "res_model": "ir.attachment",
            "view_mode": "kanban,list,form",
            "domain": [("id", "in", self.photo_ids.ids)],
        }

    def action_mark_transfer_matched(self):
        if not self.env.user.has_group(GROUPS["finance"]) and not self.env.su:
            raise AccessError(self.env._("Only Finance matches door transfers."))
        self.with_context(**{STOP_CTX: True}).write({"transfer_matched": True})
        return True

    @api.constrains("job_id", "stop_type", "earlydryer_branch_id")
    def _check_job_branch(self):
        for stop in self.filtered("job_id"):
            if stop.job_id.sudo().earlydryer_branch_id != stop.earlydryer_branch_id:
                raise ValidationError(
                    self.env._(
                        "Job %(job)s belongs to another plant than stop %(stop)s.",
                        job=stop.job_id.name,
                        stop=stop.name,
                    )
                )
