# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from ..models.earlydryer_logistics_stop import SOURCES, STOP_CTX, STOP_TYPES


class EarlydryerLogisticsScheduleSlot(models.TransientModel):
    _name = "earlydryer.logistics.schedule.slot"
    _description = "Earlydryer Slot Offered"
    _order = "start, id"

    wizard_id = fields.Many2one(
        "earlydryer.logistics.schedule.wizard", required=True, ondelete="cascade"
    )
    key = fields.Char(required=True)
    label = fields.Char(readonly=True)
    start = fields.Datetime(readonly=True)
    remaining = fields.Integer(readonly=True)
    selected = fields.Boolean()


class EarlydryerLogisticsScheduleWizard(models.TransientModel):
    """Book a pickup or arrange a delivery: quote (fee told to the
    customer), slot, fee waiver (managers), cash on delivery, notes."""

    _name = "earlydryer.logistics.schedule.wizard"
    _description = "Earlydryer Book Pickup / Arrange Delivery"

    stop_id = fields.Many2one("earlydryer.logistics.stop", string="Stop")
    stop_type = fields.Selection(STOP_TYPES, required=True, default="pickup")
    job_id = fields.Many2one("laundry.job", string="Laundry Job")
    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    address_partner_id = fields.Many2one(
        "res.partner",
        string="Address",
        domain="['|', ('id', '=', partner_id), ('parent_id', '=', partner_id)]",
    )
    address_area_id = fields.Many2one(
        related="address_partner_id.earlydryer_area_id", readonly=False
    )
    address_landmark = fields.Char(
        related="address_partner_id.earlydryer_landmark", readonly=False
    )
    branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        required=True,
        default=lambda self: self.env["earlydryer.logistics.stop"]._default_earlydryer_branch_id(),
    )
    currency_id = fields.Many2one(related="branch_id.company_id.currency_id")
    date = fields.Date(required=True, default=fields.Date.context_today)
    express = fields.Boolean()
    order_amount = fields.Monetary()
    source = fields.Selection(SOURCES, default="backend", required=True)
    # quote
    served = fields.Boolean(readonly=True)
    zone_id = fields.Many2one("earlydryer.delivery.zone", readonly=True)
    distance_km = fields.Float(readonly=True, digits=(8, 2))
    quoted_fee = fields.Monetary(readonly=True)
    fee_breakdown = fields.Text(readonly=True)
    below_minimum = fields.Boolean(readonly=True)
    message = fields.Text(readonly=True)
    slot_line_ids = fields.One2many(
        "earlydryer.logistics.schedule.slot", "wizard_id", string="Available Slots"
    )
    # fee decided
    fee_amount = fields.Monetary(string="Fee")
    fee_waived = fields.Boolean()
    fee_waive_reason = fields.Char()
    is_manager = fields.Boolean(compute="_compute_is_manager")
    # delivery
    amount_due = fields.Monetary(related="job_id.amount_due")
    cod_allowed = fields.Boolean(compute="_compute_cod_allowed")
    return_delivery = fields.Boolean(help="Pickup: deliver the order back.")
    customer_note = fields.Text()
    internal_note = fields.Text()

    @api.depends("branch_id")
    def _compute_is_manager(self):
        Stop = self.env["earlydryer.logistics.stop"]
        for wizard in self:
            wizard.is_manager = Stop._earlydryer_has_right("waive", wizard.branch_id)

    @api.depends("branch_id", "partner_id", "stop_type")
    def _compute_cod_allowed(self):
        for wizard in self:
            wizard.cod_allowed = bool(
                wizard.stop_type == "delivery"
                and wizard.branch_id.earlydryer_allow_cod
                and not wizard.partner_id.commercial_partner_id.earlydryer_cod_blocked
                and not wizard.partner_id.earlydryer_cod_blocked
            )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        stop = self.env["earlydryer.logistics.stop"].browse(values.get("stop_id") or [])
        job = self.env["laundry.job"].browse(values.get("job_id") or [])
        if stop:
            values.update(
                stop_type=stop.stop_type,
                partner_id=stop.partner_id.id,
                address_partner_id=stop._earlydryer_address().id,
                branch_id=stop.earlydryer_branch_id.id,
                job_id=stop.job_id.id,
                express=stop.express,
                customer_note=stop.customer_note,
                internal_note=stop.internal_note,
                return_delivery=stop.return_delivery,
                source=stop.source,
            )
            job = stop.job_id
        elif job:
            values.update(
                stop_type="delivery",
                partner_id=job.partner_id.id,
                address_partner_id=job._earlydryer_delivery_address().id,
                branch_id=job.earlydryer_branch_id.id,
                express=job.express,
                customer_note=job.customer_note,
            )
        if job:
            values["order_amount"] = job.sudo().amount_total
        return values

    @api.onchange(
        "partner_id", "address_partner_id", "branch_id", "date", "express",
        "order_amount", "stop_type", "address_area_id",
    )
    def _onchange_quote(self):
        if self.partner_id and (
            not self.address_partner_id
            or self.address_partner_id.commercial_partner_id
            != self.partner_id.commercial_partner_id
        ):
            self.address_partner_id = self.partner_id
        self._earlydryer_apply_quote()

    def _earlydryer_apply_quote(self):
        for wizard in self:
            if not wizard.partner_id or not wizard.branch_id:
                wizard.slot_line_ids = [Command.clear()]
                continue
            quote = self.env["earlydryer.logistics.quote"].quote(
                wizard.partner_id,
                wizard.address_partner_id,
                wizard.branch_id,
                wizard.stop_type,
                wizard.date,
                express=wizard.express,
                order_amount=wizard.order_amount,
            )
            selected = wizard.slot_line_ids.filtered("selected").key
            currency = wizard.currency_id
            wizard.update(
                {
                    "served": quote["served"],
                    "zone_id": quote["zone_id"],
                    "distance_km": quote["distance_km"] or 0.0,
                    "quoted_fee": quote["fee"],
                    "fee_amount": quote["fee"],
                    "below_minimum": quote["below_minimum"],
                    "message": quote["message"],
                    "fee_breakdown": "\n".join(
                        f"{line['label']}: {currency.symbol or ''}{line['amount']:,.2f}"
                        for line in quote["fee_breakdown"]
                    ),
                    "slot_line_ids": [Command.clear()]
                    + [
                        Command.create(
                            {
                                "key": slot["key"],
                                "label": f"{slot['label']} ({slot['remaining']} left)",
                                "start": slot["start"],
                                "remaining": slot["remaining"],
                                "selected": slot["key"] == selected,
                            }
                        )
                        for slot in quote["available_slots"]
                    ],
                }
            )

    def action_refresh(self):
        self.ensure_one()
        self._earlydryer_apply_quote()
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": self.env._("Book Pickup")
            if self.stop_type == "pickup"
            else self.env._("Arrange Delivery"),
        }

    def _earlydryer_check_fee_rights(self):
        self.ensure_one()
        Stop = self.env["earlydryer.logistics.stop"]
        currency = self.currency_id
        needs_manager = []
        if self.fee_waived:
            needs_manager.append(self.env._("waiving the fee"))
            if not (self.fee_waive_reason or "").strip():
                raise UserError(self.env._("Give the reason for waiving the fee."))
        if currency.compare_amounts(self.fee_amount, self.quoted_fee):
            needs_manager.append(self.env._("changing the quoted fee"))
        if not self.served:
            needs_manager.append(self.env._("an area that is not served"))
        if self.below_minimum:
            needs_manager.append(self.env._("an order below the zone minimum"))
        if needs_manager and not Stop._earlydryer_has_right("waive", self.branch_id):
            raise UserError(
                self.env._(
                    "A Branch Manager must approve %(what)s.",
                    what=", ".join(needs_manager),
                )
            )

    def action_confirm(self):
        self.ensure_one()
        Stop = self.env["earlydryer.logistics.stop"]
        Stop._earlydryer_check_right("book", self.branch_id)
        if self.stop_type == "delivery" and not self.job_id:
            raise UserError(self.env._("Choose the job to deliver."))
        slot = self.slot_line_ids.filtered("selected")
        if len(slot) != 1:
            raise UserError(self.env._("Tick exactly one slot."))
        self._earlydryer_check_fee_rights()
        if self.fee_amount < 0:
            raise UserError(self.env._("The fee cannot be negative."))
        vals = {
            "stop_type": self.stop_type,
            "partner_id": self.partner_id.id,
            "address_partner_id": (self.address_partner_id or self.partner_id).id,
            "earlydryer_branch_id": self.branch_id.id,
            "job_id": self.job_id.id,
            "express": self.express,
            "order_amount": self.order_amount,
            "zone_id": self.zone_id.id,
            "distance_km": self.distance_km,
            "quote_message": (self.message or "")[:255] or False,
            "customer_note": self.customer_note,
            "internal_note": self.internal_note,
            "return_delivery": self.return_delivery,
            "source": self.source,
        }
        # fee fields after the checks above (managers); the stop engine
        # writes them so the draft stop keeps them
        fee_vals = {
            "fee_amount": self.fee_amount,
            "fee_waived": self.fee_waived,
            "fee_waive_reason": self.fee_waive_reason or False,
        }
        stop = self.stop_id
        if stop:
            if stop.state != "draft":
                raise UserError(self.env._("Stop %(stop)s is already scheduled.", stop=stop.name))
            stop.write(vals)
        else:
            stop = Stop.create(vals)
        stop.with_context(**{STOP_CTX: True}).write(fee_vals)
        stop._earlydryer_set_slot(slot.key)
        stop.action_schedule()
        if self.job_id and self.stop_type == "delivery" and self.job_id.fulfilment != "deliver":
            self.job_id.sudo().fulfilment = "deliver"
        return {
            "type": "ir.actions.act_window",
            "res_model": "earlydryer.logistics.stop",
            "res_id": stop.id,
            "view_mode": "form",
            "target": "current",
        }
