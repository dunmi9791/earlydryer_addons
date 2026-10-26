# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command

from .earlydryer_logistics_stop import CLOSED_STATES, GROUPS, STOP_CTX

TRIP_STATES = [
    ("draft", "Draft"),
    ("planned", "Planned"),
    ("in_progress", "In Progress"),
    ("done", "Done"),
    ("cancelled", "Cancelled"),
]
# context key: the trip engine writes the protected fields
TRIP_CTX = "earlydryer_logistics_trip_engine"
TRIP_PROTECTED = {
    "state",
    "started_on",
    "ended_on",
    "cash_counted",
    "handover_move_id",
    "difference_move_id",
    "carrier_bill_id",
}


class EarlydryerLogisticsTrip(models.Model):
    _name = "earlydryer.logistics.trip"
    _description = "Earlydryer Delivery Trip"
    _inherit = ["mail.thread", "mail.activity.mixin", "earlydryer.branch.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: self.env._("New"),
    )
    date = fields.Date(
        required=True, default=fields.Date.context_today, index=True, tracking=True
    )
    slot = fields.Char(help='Optional label, e.g. "Morning run".')
    state = fields.Selection(
        TRIP_STATES,
        required=True,
        default="draft",
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        related="earlydryer_branch_id.company_id", store=True, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    rider_employee_id = fields.Many2one(
        "hr.employee",
        string="Rider",
        tracking=True,
        index=True,
        help="An employee whose user is a Rider, or an employee flagged as a "
        "rider without a login (the office records the outcomes).",
    )
    rider_user_id = fields.Many2one(
        related="rider_employee_id.user_id", store=True, string="Rider User"
    )
    vehicle_id = fields.Many2one("fleet.vehicle", string="Vehicle", tracking=True)
    carrier_partner_id = fields.Many2one(
        "res.partner",
        string="Carrier (3PL)",
        domain=[("earlydryer_is_carrier", "=", True)],
        tracking=True,
    )
    carrier_reference = fields.Char(tracking=True)
    carrier_fee = fields.Monetary(tracking=True)
    carrier_bill_id = fields.Many2one(
        "account.move", string="Carrier Bill", readonly=True, copy=False
    )
    is_carrier = fields.Boolean(compute="_compute_is_carrier", store=True)
    stop_ids = fields.One2many("earlydryer.logistics.stop", "trip_id", string="Stops")
    stop_count = fields.Integer(compute="_compute_counts", store=True)
    done_count = fields.Integer(compute="_compute_counts", store=True)
    failed_count = fields.Integer(compute="_compute_counts", store=True)
    not_loaded_count = fields.Integer(compute="_compute_not_loaded_count")
    cod_total = fields.Monetary(
        string="COD to Collect", compute="_compute_counts", store=True
    )
    started_on = fields.Datetime(readonly=True, copy=False)
    ended_on = fields.Datetime(readonly=True, copy=False)
    odometer_start = fields.Float(copy=False)
    odometer_end = fields.Float(copy=False)
    odometer_id = fields.Many2one("fleet.vehicle.odometer", readonly=True, copy=False)
    cash_expected = fields.Monetary(compute="_compute_cash", store=True)
    cash_counted = fields.Monetary(readonly=True, copy=False, tracking=True)
    cash_difference = fields.Monetary(compute="_compute_cash", store=True)
    handover_move_id = fields.Many2one(
        "account.move", string="Handover Entry", readonly=True, copy=False
    )
    difference_move_id = fields.Many2one(
        "account.move", string="Cash Difference Entry", readonly=True, copy=False
    )
    note = fields.Text()

    @api.depends("carrier_partner_id")
    def _compute_is_carrier(self):
        for trip in self:
            trip.is_carrier = bool(trip.carrier_partner_id)

    @api.depends("stop_ids.state", "stop_ids.cod_amount")
    def _compute_counts(self):
        for trip in self:
            stops = trip.stop_ids.filtered(lambda s: s.state != "cancelled")
            trip.stop_count = len(stops)
            trip.done_count = len(stops.filtered(lambda s: s.state == "done"))
            trip.failed_count = len(stops.filtered(lambda s: s.state == "failed"))
            trip.cod_total = sum(stops.mapped("cod_amount"))

    def _compute_not_loaded_count(self):
        for trip in self:
            trip.not_loaded_count = len(trip.stop_ids.filtered("not_loaded"))

    @api.depends(
        "stop_ids.cash_collected", "stop_ids.collection_method", "cash_counted", "state"
    )
    def _compute_cash(self):
        for trip in self:
            expected = sum(
                trip.stop_ids.filtered(lambda s: s.collection_method == "cash").mapped(
                    "cash_collected"
                )
            )
            trip.cash_expected = expected
            trip.cash_difference = (
                trip.cash_counted - expected if trip.state == "done" else 0.0
            )

    @api.constrains("rider_employee_id", "carrier_partner_id")
    def _check_rider_or_carrier(self):
        for trip in self:
            if trip.rider_employee_id and trip.carrier_partner_id:
                raise ValidationError(
                    self.env._(
                        "Trip %(trip)s: choose a rider or a carrier, not both.",
                        trip=trip.name,
                    )
                )

    @api.depends("name", "rider_employee_id", "carrier_partner_id", "slot")
    def _compute_display_name(self):
        for trip in self:
            who = (
                trip.rider_employee_id.sudo().name
                or trip.carrier_partner_id.sudo().name
            )
            parts = [trip.name, trip.slot, who]
            trip.display_name = " - ".join(part for part in parts if part)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _stop_model(self):
        return self.env["earlydryer.logistics.stop"]

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.context.get(TRIP_CTX):
            branches = self.env["earlydryer.branch"].browse(
                [
                    vals.get("earlydryer_branch_id")
                    for vals in vals_list
                    if vals.get("earlydryer_branch_id")
                ]
            )
            self._stop_model()._earlydryer_check_right("plan", branches or None)
            for vals in vals_list:
                if TRIP_PROTECTED & set(vals):
                    raise UserError(
                        self.env._("These trip fields are set by the system.")
                    )
        trips = super().create(vals_list)
        for trip in trips:
            if not trip.name or trip.name == self.env._("New"):
                sequence = (
                    trip.earlydryer_branch_id._earlydryer_logistics_ensure_sequences()[
                        "trip"
                    ]
                )
                trip.name = sequence.sudo().next_by_id()
        return trips

    def write(self, vals):
        if not self.env.su and not self.env.context.get(TRIP_CTX):
            if TRIP_PROTECTED & set(vals):
                raise UserError(
                    self.env._(
                        "Use the trip buttons: states and cash are set by the system."
                    )
                )
            self._stop_model()._earlydryer_check_right(
                "plan", self.earlydryer_branch_id
            )
            if {
                "rider_employee_id",
                "carrier_partner_id",
                "earlydryer_branch_id",
            } & set(vals) and any(
                trip.state in ("in_progress", "done") for trip in self
            ):
                raise UserError(
                    self.env._("The rider or carrier of a started trip cannot change.")
                )
        return super().write(vals)

    def unlink(self):
        if any(trip.state not in ("draft", "cancelled") for trip in self):
            raise UserError(self.env._("Only draft or cancelled trips can be deleted."))
        self.stop_ids.with_context(**{STOP_CTX: True}).write({"trip_id": False})
        return super().unlink()

    # ------------------------------------------------------------------
    # Planning and start
    # ------------------------------------------------------------------

    def _engine(self):
        return self.with_context(**{TRIP_CTX: True})

    def action_plan(self):
        self._stop_model()._earlydryer_check_right("plan", self.earlydryer_branch_id)
        for trip in self:
            if trip.state != "draft":
                raise UserError(
                    self.env._("Trip %(trip)s is not a draft.", trip=trip.name)
                )
            if not trip.rider_employee_id and not trip.carrier_partner_id:
                raise UserError(
                    self.env._(
                        "Choose the rider or the carrier of %(trip)s.", trip=trip.name
                    )
                )
            if not trip.stop_ids.filtered(lambda s: s.state != "cancelled"):
                raise UserError(
                    self.env._("Trip %(trip)s has no stop.", trip=trip.name)
                )
            trip._engine().state = "planned"
            trip.stop_ids._earlydryer_refresh_cod()
        return True

    def action_back_to_draft(self):
        self._stop_model()._earlydryer_check_right("plan", self.earlydryer_branch_id)
        for trip in self:
            if trip.state != "planned":
                raise UserError(self.env._("Only planned trips go back to draft."))
            trip._engine().state = "draft"
        return True

    def _earlydryer_start(self, odometer=None):
        """Planned → In Progress. Pickups are under way at once; deliveries
        wait for their bag scan (a 3PL takes every delivery at once)."""
        self.ensure_one()
        if self.state == "in_progress":
            return True
        if self.state != "planned":
            raise UserError(self.env._("Plan trip %(trip)s first.", trip=self.name))
        vals = {"state": "in_progress", "started_on": fields.Datetime.now()}
        if odometer not in (None, False, ""):
            vals["odometer_start"] = float(odometer)
        elif self.vehicle_id and not self.odometer_start:
            vals["odometer_start"] = self.vehicle_id.sudo().odometer
        self._engine().write(vals)
        stops = self.stop_ids.filtered(lambda s: s.state == "assigned")
        stops.filtered(lambda s: s.stop_type == "pickup").with_context(
            **{STOP_CTX: True}
        ).write({"state": "en_route"})
        if self.is_carrier:
            for stop in stops.filtered(lambda s: s.stop_type == "delivery"):
                self._earlydryer_load(stop)
        return True

    def action_start(self):
        self._stop_model()._earlydryer_check_right("plan", self.earlydryer_branch_id)
        for trip in self:
            trip._earlydryer_start()
        return True

    def _earlydryer_load(self, stop):
        """The garments of a delivery are on board: job Out for Delivery
        (release check: paid, credit approved or covered by the COD)."""
        self.ensure_one()
        if stop.loaded:
            return True
        stop._earlydryer_refresh_cod()
        job = stop.job_id.sudo()
        employee = self.rider_employee_id.sudo()
        if job.state != "out_for_delivery":
            job.action_move_to(
                "out_for_delivery",
                employee=employee,
                note=self.env._("Loaded on trip %(trip)s", trip=self.name),
            )
        stop.with_context(**{STOP_CTX: True}).write(
            {"loaded": True, "loaded_on": fields.Datetime.now(), "state": "en_route"}
        )
        return True

    def _earlydryer_scan(self, code):
        """Bag label (job number) or garment tag scanned onto the trip.

        :returns: ``{"result": ok|duplicate|not_on_trip|refused|unknown|
            invalid, "stop_id", "job_name", "message"}``
        """
        self.ensure_one()
        if self.state != "in_progress":
            return {
                "result": "refused",
                "stop_id": False,
                "job_name": False,
                "message": self.env._("Start the trip before scanning bags."),
            }
        lookup = self.env["laundry.job"].earlydryer_scan_lookup(
            code, branch_id=self.earlydryer_branch_id.id
        )
        result = {
            "result": lookup["type"]
            if lookup["type"] in ("unknown", "invalid")
            else "ok",
            "stop_id": False,
            "job_name": lookup.get("job_name") or False,
            "message": lookup.get("message") or "",
        }
        if lookup["type"] not in ("item", "job"):
            return result
        job = self.env["laundry.job"].browse(lookup["job_id"])
        stop = self.stop_ids.filtered(
            lambda s: (
                s.stop_type == "delivery"
                and s.state not in CLOSED_STATES
                and (s.job_id == job or job in s.job_ids)
            )
        )[:1]
        if not stop:
            result.update(
                result="not_on_trip",
                message=self.env._("Job %(job)s is not on this trip.", job=job.name),
            )
            return result
        result["stop_id"] = stop.id
        if stop.loaded:
            result.update(
                result="duplicate",
                message=self.env._("%(job)s is already on board.", job=job.name),
            )
            return result
        try:
            with self.env.cr.savepoint():
                self._earlydryer_load(stop)
        except UserError as error:
            result.update(result="refused", message=str(error))
            return result
        result["message"] = self.env._(
            "%(job)s on board for %(customer)s.",
            job=job.name,
            customer=stop.partner_id.name,
        )
        return result

    def action_scan(self, code):
        """Backend / scanner entry point."""
        self.ensure_one()
        self.check_access("write")
        return self._earlydryer_scan(code)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _earlydryer_check_closable(self):
        self.ensure_one()
        if self.state != "in_progress":
            raise UserError(
                self.env._("Trip %(trip)s is not in progress.", trip=self.name)
            )
        open_stops = self.stop_ids.filtered(lambda s: s.state not in CLOSED_STATES)
        if open_stops:
            raise UserError(
                self.env._(
                    "Record the outcome of every stop first: %(stops)s.",
                    stops=", ".join(open_stops.mapped("name")),
                )
            )

    def _earlydryer_short_account(self):
        """``(account, partner)`` debited with a rider cash shortage."""
        self.ensure_one()
        company = self.company_id.sudo()
        if company.earlydryer_rider_short_mode == "cash_short":
            account = company.earlydryer_cash_diff_account_id
            if not account:
                raise UserError(
                    self.env._(
                        "Set the Cash over and short account (accounting setup)."
                    )
                )
            return account, self.env["res.partner"]
        employee = self.rider_employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        account = company.earlydryer_rider_receivable_account_id or (
            partner.property_account_receivable_id if partner else False
        )
        if not account:
            raise UserError(
                self.env._(
                    "Set the rider receivable account in the logistics settings."
                )
            )
        return account, partner

    def _earlydryer_post_difference(self, difference):
        """Shortage: Dr rider receivable or cash short / Cr rider cash.
        Overage: Dr rider cash / Cr cash over and short. Never written off
        silently: the entry names the trip and the rider."""
        self.ensure_one()
        branch = self.earlydryer_branch_id.sudo()
        rider_account = branch.earlydryer_rider_account_id
        company = self.company_id.sudo()
        label = self.env._(
            "Rider cash difference %(trip)s: %(rider)s",
            trip=self.name,
            rider=self.rider_employee_id.sudo().name
            or self.carrier_partner_id.name
            or "-",
        )
        if difference < 0:
            account, partner = self._earlydryer_short_account()
            lines = [
                {
                    "account_id": account.id,
                    "debit": -difference,
                    "partner_id": partner.id,
                },
                {"account_id": rider_account.id, "credit": -difference},
            ]
        else:
            account = company.earlydryer_cash_diff_account_id
            if not account:
                raise UserError(
                    self.env._(
                        "Set the Cash over and short account (accounting setup)."
                    )
                )
            lines = [
                {"account_id": rider_account.id, "debit": difference},
                {"account_id": account.id, "credit": difference},
            ]
        move = (
            self.env["account.move"]
            .sudo()
            .with_context(earlydryer_move_branch_id=branch.id)
            .create(
                {
                    "move_type": "entry",
                    "journal_id": branch.earlydryer_rider_journal_id.id,
                    "date": fields.Date.context_today(self),
                    "ref": label,
                    "earlydryer_branch_id": branch.id,
                    "earlydryer_rider_employee_id": self.rider_employee_id.id or False,
                    "earlydryer_logistics_trip_id": self.id,
                    "line_ids": [
                        Command.create({"name": label, **line}) for line in lines
                    ],
                }
            )
        )
        move.action_post()
        return move

    def _earlydryer_close(self, cash_counted, odometer_end=None, note=None):
        """Close the trip: every stop resolved, the counted cash handed over
        to the plant, the difference posted and alerted, the odometer logged."""
        self.ensure_one()
        self._stop_model()._earlydryer_check_right("close", self.earlydryer_branch_id)
        self._earlydryer_check_closable()
        currency = self.currency_id or self.env.company.currency_id
        counted = currency.round(float(cash_counted or 0.0))
        if counted < 0:
            raise UserError(self.env._("The cash counted cannot be negative."))
        expected = self.cash_expected
        difference = currency.round(counted - expected)
        vals = {
            "state": "done",
            "ended_on": fields.Datetime.now(),
            "cash_counted": counted,
        }
        if currency.compare_amounts(counted, 0.0) > 0:
            vals["handover_move_id"] = (
                self.env["account.move"]
                ._earlydryer_rider_handover(
                    self.earlydryer_branch_id,
                    counted,
                    self.rider_employee_id,
                    ref=self.name,
                )
                .id
            )
        if not currency.is_zero(difference):
            vals["difference_move_id"] = self._earlydryer_post_difference(difference).id
        if odometer_end not in (None, False, ""):
            vals["odometer_end"] = float(odometer_end)
        if note:
            vals["note"] = "\n".join(filter(None, [self.note, note]))
        self._engine().write(vals)
        if self.vehicle_id and self.odometer_end:
            if self.odometer_start and self.odometer_end < self.odometer_start:
                raise UserError(
                    self.env._("The odometer at the end is below the start reading.")
                )
            odometer = (
                self.env["fleet.vehicle.odometer"]
                .sudo()
                .create(
                    {
                        "vehicle_id": self.vehicle_id.id,
                        "value": self.odometer_end,
                        "date": fields.Date.context_today(self),
                    }
                )
            )
            self._engine().odometer_id = odometer
        # plant arrival time of the bags picked up on this trip
        self.stop_ids.filtered(
            lambda s: s.stop_type == "pickup" and s.state == "done"
        )._earlydryer_mark_at_plant()
        if currency.compare_amounts(difference, 0.0) < 0:
            self.env["earlydryer.notify.message"].notify(
                "alert_rider_cash_short",
                self,
                context={
                    "value": -difference,
                    "occurrence": f"close:{self.id}",
                    "summary": self.env._(
                        "Trip %(trip)s (%(rider)s): expected %(expected)s, counted "
                        "%(counted)s",
                        trip=self.name,
                        rider=self.rider_employee_id.sudo().name or "-",
                        expected=self._earlydryer_format(expected),
                        counted=self._earlydryer_format(counted),
                    ),
                },
            )
        return True

    def _earlydryer_format(self, amount):
        currency = self.currency_id or self.env.company.currency_id
        return f"{currency.symbol or ''}{amount or 0.0:,.2f}"

    def action_open_close_wizard(self):
        self.ensure_one()
        self._stop_model()._earlydryer_check_right("close", self.earlydryer_branch_id)
        self._earlydryer_check_closable()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Close Trip %s", self.name),
            "res_model": "earlydryer.logistics.close.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_trip_id": self.id},
        }

    def action_cancel(self):
        self._stop_model()._earlydryer_check_right("plan", self.earlydryer_branch_id)
        for trip in self:
            if trip.state not in ("draft", "planned"):
                raise UserError(
                    self.env._("Only draft or planned trips can be cancelled.")
                )
            trip.stop_ids.filtered(
                lambda s: s.state in ("scheduled", "assigned")
            ).write({"trip_id": False})
            trip._engine().state = "cancelled"
        return True

    # ------------------------------------------------------------------
    # 3PL
    # ------------------------------------------------------------------

    def action_create_carrier_bill(self):
        """Draft vendor bill of the carrier's fee (WHT from accounting_ng)."""
        self.ensure_one()
        self._stop_model()._earlydryer_check_right("close", self.earlydryer_branch_id)
        if not self.carrier_partner_id:
            raise UserError(self.env._("Trip %(trip)s has no carrier.", trip=self.name))
        if self.carrier_bill_id:
            return self.action_view_carrier_bill()
        if self.currency_id.compare_amounts(self.carrier_fee, 0.0) <= 0:
            raise UserError(self.env._("Set the carrier fee first."))
        company = self.company_id.sudo()
        account = (
            company.earlydryer_carrier_expense_account_id or company.expense_account_id
        )
        if not account:
            raise UserError(
                self.env._("Set the 3PL expense account in the logistics settings.")
            )
        branch = self.earlydryer_branch_id.sudo()
        line = {
            "name": self.env._(
                "Delivery services %(trip)s %(date)s %(ref)s",
                trip=self.name,
                date=fields.Date.to_string(self.date),
                ref=self.carrier_reference or "",
            ).strip(),
            "quantity": 1,
            "price_unit": self.carrier_fee,
            "account_id": account.id,
        }
        if branch.analytic_account_id:
            line["analytic_distribution"] = {str(branch.analytic_account_id.id): 100}
        bill = (
            self.env["account.move"]
            .sudo()
            .with_context(earlydryer_move_branch_id=branch.id)
            .create(
                {
                    "move_type": "in_invoice",
                    "partner_id": self.carrier_partner_id.id,
                    "invoice_date": self.date,
                    "ref": self.carrier_reference or self.name,
                    "earlydryer_branch_id": branch.id,
                    "earlydryer_logistics_trip_id": self.id,
                    "invoice_line_ids": [Command.create(line)],
                }
            )
        )
        self._engine().carrier_bill_id = bill
        return self.action_view_carrier_bill()

    def action_view_carrier_bill(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.carrier_bill_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_print_route_sheet(self):
        return self.env.ref(
            "earlydryer_logistics.action_report_route_sheet"
        ).report_action(self)

    def action_view_stops(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Stops of %s", self.name),
            "res_model": "earlydryer.logistics.stop",
            "view_mode": "list,form",
            "domain": [("trip_id", "=", self.id)],
            "context": {"default_trip_id": self.id},
        }

    def _earlydryer_is_rider_of(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        return bool(self.rider_employee_id.sudo().user_id == user)

    def _earlydryer_has_manager_rights(self):
        return self.env.su or self.env.user.has_group(GROUPS["branch_manager"])
