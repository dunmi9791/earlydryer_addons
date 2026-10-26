# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain

WEEKDAYS = [
    ("0", "Monday"),
    ("1", "Tuesday"),
    ("2", "Wednesday"),
    ("3", "Thursday"),
    ("4", "Friday"),
    ("5", "Saturday"),
    ("6", "Sunday"),
]
DEFAULT_TZ = "Africa/Lagos"
# stop states that no longer hold a place in a slot
FREE_STATES = ("cancelled",)


def float_to_time(value):
    hours = int(value)
    minutes = int(round((value - hours) * 60))
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return time(min(hours, 23), minutes)


class EarlydryerLogisticsSlotTemplate(models.Model):
    """Weekly pickup / delivery window of a plant."""

    _name = "earlydryer.logistics.slot.template"
    _description = "Earlydryer Pickup/Delivery Slot"
    # mail.thread: the branch field of the mixin is tracked
    _inherit = ["mail.thread", "earlydryer.branch.mixin"]
    _order = "earlydryer_branch_id, weekday, start_time"

    name = fields.Char(required=True, help='Label shown to staff, e.g. "Morning".')
    weekday = fields.Selection(WEEKDAYS, required=True, default="0")
    start_time = fields.Float(required=True, default=9.0, help="Local time (hours).")
    end_time = fields.Float(required=True, default=12.0)
    stop_type = fields.Selection(
        [("pickup", "Pickups"), ("delivery", "Deliveries"), ("both", "Both")],
        required=True,
        default="both",
    )
    capacity = fields.Integer(default=10, help="Maximum stops in this slot.")
    cutoff_hours = fields.Float(
        default=2.0,
        help="Bookings close this many hours before the slot starts.",
    )
    zone_ids = fields.Many2many(
        "earlydryer.delivery.zone",
        string="Zones",
        domain="[('earlydryer_branch_id', '=', earlydryer_branch_id)]",
        help="Zones served in this slot (empty = all zones of the plant).",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        related="earlydryer_branch_id.company_id", store=True, index=True
    )

    @api.constrains("start_time", "end_time", "capacity", "cutoff_hours")
    def _check_times(self):
        for slot in self:
            if not 0 <= slot.start_time < slot.end_time <= 24:
                raise ValidationError(
                    self.env._("Slot %(slot)s: the end must follow the start.",
                               slot=slot.name)
                )
            if slot.capacity < 0 or slot.cutoff_hours < 0:
                raise ValidationError(
                    self.env._("Capacity and cut-off cannot be negative.")
                )

    @api.depends("name", "weekday", "start_time", "end_time")
    def _compute_display_name(self):
        days = dict(WEEKDAYS)
        for slot in self:
            slot.display_name = (
                f"{days.get(slot.weekday, '')} {slot.name} "
                f"({float_to_time(slot.start_time):%H:%M}-"
                f"{float_to_time(slot.end_time):%H:%M})"
            )

    # ------------------------------------------------------------------
    # Concrete slots
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_tz(self, branch):
        tz_name = (
            branch.resource_calendar_id.tz
            or branch.partner_id.tz
            or branch.company_id.partner_id.tz
            or DEFAULT_TZ
        )
        try:
            return ZoneInfo(tz_name)
        except (KeyError, ValueError):
            return ZoneInfo(DEFAULT_TZ)

    def _earlydryer_bounds(self, day):
        """``(start, end)`` of this template on ``day``, naive UTC."""
        self.ensure_one()
        tz = self._earlydryer_tz(self.earlydryer_branch_id)
        utc = ZoneInfo("UTC")
        start = datetime.combine(day, float_to_time(self.start_time), tzinfo=tz)
        if self.end_time >= 24:
            end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
        else:
            end = datetime.combine(day, float_to_time(self.end_time), tzinfo=tz)
        return (
            start.astimezone(utc).replace(tzinfo=None),
            end.astimezone(utc).replace(tzinfo=None),
        )

    @api.model
    def _earlydryer_holidays(self, branch, start, end):
        """Public holidays (resource leaves without resource) of the plant's
        calendar or of no calendar, overlapping ``[start, end]``."""
        domain = Domain("resource_id", "=", False) & Domain(
            "date_from", "<", end
        ) & Domain("date_to", ">", start) & Domain(
            "company_id", "in", [branch.company_id.id, False]
        )
        calendar = branch.resource_calendar_id
        domain &= Domain("calendar_id", "in", [calendar.id, False] if calendar else [False])
        return self.env["resource.calendar.leaves"].sudo().search(domain)

    @api.model
    def _earlydryer_usage(self, templates, date_from, date_to):
        """``{(template_id, date): booked stops}``."""
        groups = self.env["earlydryer.logistics.stop"].sudo()._read_group(
            [
                ("slot_template_id", "in", templates.ids),
                ("slot_date", ">=", date_from),
                ("slot_date", "<=", date_to),
                ("state", "not in", FREE_STATES),
            ],
            ["slot_template_id", "slot_date:day"],
            ["__count"],
        )
        return {
            (template.id, fields.Date.to_date(day)): count
            for template, day, count in groups
        }

    @api.model
    def _earlydryer_slot_key(self, template, day):
        return f"{fields.Date.to_string(day)}|{template.id}"

    @api.model
    def _earlydryer_parse_key(self, key):
        """``(template, date)`` of a slot key, or empty template."""
        try:
            day, template_id = (key or "").split("|")
            return self.browse(int(template_id)).exists(), fields.Date.to_date(day)
        except (ValueError, TypeError):
            return self.browse(), False

    @api.model
    def available_slots(
        self, branch, stop_type, date_from, date_to, zone=None, now=None,
        include_full=False,
    ):
        """Concrete slots of ``branch`` between two dates (included).

        Past slots, slots inside their cut-off and public holidays are
        skipped; slots without capacity left too unless ``include_full``.

        :returns: list of JSON-safe dicts ``{"key", "template_id", "name",
            "date", "start", "end", "label", "capacity", "booked",
            "remaining"}`` sorted by start (datetimes naive UTC strings)
        """
        branch.ensure_one()
        now = now or fields.Datetime.now()
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to or date_from)
        domain = [
            ("earlydryer_branch_id", "=", branch.id),
            ("stop_type", "in", [stop_type, "both"]),
        ]
        templates = self.sudo().search(domain)
        if zone:
            templates = templates.filtered(
                lambda t: not t.zone_ids or zone in t.zone_ids
            )
        if not templates:
            return []
        usage = self._earlydryer_usage(templates, date_from, date_to)
        holidays = self._earlydryer_holidays(
            branch,
            datetime.combine(date_from, time(0)) - timedelta(days=1),
            datetime.combine(date_to, time(0)) + timedelta(days=2),
        )
        slots = []
        day = date_from
        while day <= date_to:
            for template in templates.filtered(lambda t, d=day: int(t.weekday) == d.weekday()):
                start, end = template._earlydryer_bounds(day)
                if start - timedelta(hours=template.cutoff_hours) < now:
                    continue
                if any(
                    leave.date_from < end and leave.date_to > start
                    for leave in holidays
                ):
                    continue
                booked = usage.get((template.id, day), 0)
                remaining = max(template.capacity - booked, 0)
                if not remaining and not include_full:
                    continue
                tz = self._earlydryer_tz(branch)
                local_start = start.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
                local_end = end.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
                slots.append(
                    {
                        "key": self._earlydryer_slot_key(template, day),
                        "template_id": template.id,
                        "name": template.name,
                        "date": fields.Date.to_string(day),
                        "start": fields.Datetime.to_string(start),
                        "end": fields.Datetime.to_string(end),
                        "label": f"{local_start:%a %d %b} {template.name} "
                        f"{local_start:%H:%M}-{local_end:%H:%M}",
                        "capacity": template.capacity,
                        "booked": booked,
                        "remaining": remaining,
                    }
                )
            day += timedelta(days=1)
        slots.sort(key=lambda slot: (slot["start"], slot["template_id"]))
        return slots
