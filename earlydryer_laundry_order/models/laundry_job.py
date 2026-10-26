# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import float_round

_logger = logging.getLogger(__name__)

STATES = [
    ("received", "Received"),
    ("tagged", "Tagged"),
    ("sorted", "Sorted"),
    ("washed", "Washed"),
    ("dried", "Dried"),
    ("ironed", "Ironed"),
    ("qc", "QC"),
    ("packed", "Packed"),
    ("ready", "Ready"),
    ("out_for_delivery", "Out for Delivery"),
    ("delivered", "Delivered"),
    ("collected", "Collected"),
    ("uncollected", "Uncollected"),
    ("cancelled", "Cancelled"),
]
# normal path through the plant, up to the shelf
FORWARD_PATH = [
    "received",
    "tagged",
    "sorted",
    "washed",
    "dried",
    "ironed",
    "qc",
    "packed",
    "ready",
]
# stages where the employee who did the work must be recorded
PRODUCTION_STATES = {"sorted", "washed", "dried", "ironed", "qc", "packed"}
FINAL_STATES = {"delivered", "collected", "uncollected", "cancelled"}
# leaving the plant: payment or approved credit needed
RELEASE_STATES = {"collected", "out_for_delivery"}
# where a QC failure can send a job back to
REWORK_STATES = ["sorted", "washed", "ironed"]

CHANNELS = [
    ("walk_in", "Walk-in"),
    ("pickup", "Pickup"),
    ("website", "Website"),
    ("whatsapp", "WhatsApp"),
    ("phone", "Phone"),
    ("corporate", "Corporate"),
]
FULFILMENTS = [("collect", "Collect at Plant"), ("deliver", "Delivery")]

MANAGER_GROUP = "earlydryer_base.group_branch_manager"
# context key set by the stage-move engine, the only writer of ``state``
MOVE_CTX = "earlydryer_stage_move"
# context key carrying the reason of a manager's correction of locked items
CORRECTION_CTX = "earlydryer_correction_reason"
TODO_ACTIVITY = "mail.mail_activity_data_todo"


class LaundryJob(models.Model):
    _name = "laundry.job"
    _description = "Laundry Job"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
        "earlydryer.branch.mixin",
        "earlydryer.approval.mixin",
    ]
    _order = "received_on desc, id desc"
    _rec_names_search = ["name", "partner_id.name", "partner_phone"]

    name = fields.Char(
        string="Number",
        required=True,
        readonly=True,
        index=True,
        copy=False,
        default=lambda self: self.env._("New"),
    )
    state = fields.Selection(
        STATES,
        string="Stage",
        required=True,
        default="received",
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
        group_expand=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        tracking=True,
        index=True,
    )
    partner_phone = fields.Char(
        related="partner_id.phone", string="Phone", store=True, index="trigram"
    )
    channel = fields.Selection(CHANNELS, required=True, default="walk_in")
    fulfilment = fields.Selection(FULFILMENTS, required=True, default="collect")
    express = fields.Boolean(tracking=True)
    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sales Order",
        index="btree_not_null",
        copy=False,
        ondelete="restrict",
    )
    pos_order_id = fields.Many2one(
        "pos.order",
        string="POS Order",
        index="btree_not_null",
        copy=False,
        ondelete="restrict",
    )
    company_id = fields.Many2one(
        related="earlydryer_branch_id.company_id", store=True, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    item_ids = fields.One2many("laundry.job.item", "job_id", string="Items", copy=True)
    item_count = fields.Integer(compute="_compute_item_count", store=True)
    received_on = fields.Datetime(
        required=True, default=fields.Datetime.now, copy=False
    )
    promised_on = fields.Datetime(
        compute="_compute_promised_on",
        store=True,
        readonly=False,
        tracking=True,
        copy=False,
        help="Computed from the turnaround of the items while the job is "
        "Received. Afterwards only a Branch Manager can change it.",
    )
    ready_on = fields.Datetime(readonly=True, copy=False)
    closed_on = fields.Datetime(readonly=True, copy=False)
    shelf_id = fields.Many2one(
        "earlydryer.branch.shelf",
        string="Shelf",
        tracking=True,
        copy=False,
        domain="[('branch_id', '=', earlydryer_branch_id)]",
    )
    amount_total = fields.Monetary(
        compute="_compute_amounts",
        compute_sudo=True,
        help="Total of the sales or POS order: garments, surcharges, express "
        "and retail lines.",
    )
    amount_paid = fields.Monetary(compute="_compute_amounts", compute_sudo=True)
    amount_due = fields.Monetary(compute="_compute_amounts", compute_sudo=True)
    is_unpaid = fields.Boolean(
        string="Unpaid",
        compute="_compute_amounts",
        compute_sudo=True,
        search="_search_is_unpaid",
    )
    is_overdue = fields.Boolean(
        string="Overdue", compute="_compute_is_overdue", search="_search_is_overdue"
    )
    stage_log_ids = fields.One2many(
        "laundry.job.stage.log", "job_id", string="Stage History", readonly=True
    )
    next_state = fields.Selection(STATES, compute="_compute_next_state")
    uncollected_reminders_sent = fields.Char(
        readonly=True,
        copy=False,
        help="Days after Ready on which the collection reminder was sent.",
    )
    cancel_reason = fields.Text(copy=False)
    note = fields.Html(string="Internal Notes")
    customer_note = fields.Text(
        string="Customer Instructions", help='Instructions such as "no starch".'
    )
    correction_reason = fields.Char(
        compute="_compute_correction_reason",
        inverse="_inverse_correction_reason",
        help="Required from a Branch Manager to change the items after intake.",
    )
    missing_item_count = fields.Integer(compute="_compute_missing_item_count")

    _sale_order_uniq = models.Constraint(
        "unique(sale_order_id)", "A sales order creates at most one laundry job."
    )
    _pos_order_uniq = models.Constraint(
        "unique(pos_order_id)", "A POS order creates at most one laundry job."
    )
    _single_source = models.Constraint(
        "CHECK(sale_order_id IS NULL OR pos_order_id IS NULL)",
        "A laundry job comes from a sales order or a POS order, not both.",
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends("item_ids")
    def _compute_item_count(self):
        for job in self:
            job.item_count = len(job.item_ids)

    @api.depends("item_ids.missing")
    def _compute_missing_item_count(self):
        for job in self:
            job.missing_item_count = len(job.item_ids.filtered("missing"))

    @api.depends(
        "item_ids.product_id", "express", "received_on", "earlydryer_branch_id"
    )
    def _compute_promised_on(self):
        Catalog = self.env["earlydryer.catalog"]
        for job in self:
            # the promise is only computed at intake; afterwards it is kept
            if job.state != "received" or not job.received_on:
                continue
            products = job.item_ids.product_id
            if not products:
                continue
            job.promised_on = Catalog.promised_datetime(
                products,
                job.earlydryer_branch_id,
                express=job.express,
                start=job.received_on,
            )

    def _compute_amounts(self):
        for job in self:
            amounts = job._earlydryer_amounts()
            total = amounts["total"]
            paid = amounts["paid"] + job._earlydryer_extra_paid()
            currency = job.currency_id or self.env.company.currency_id
            due = currency.round(max(total - paid, 0.0))
            job.amount_total = total
            job.amount_paid = paid
            job.amount_due = due
            job.is_unpaid = currency.compare_amounts(due, 0.0) > 0

    def _search_is_unpaid(self, operator, value):
        if operator not in ("in", "not in"):
            return NotImplemented
        # amounts depend on invoices and payments, so they are not stored:
        # evaluate the open jobs only (a bounded set)
        open_jobs = self.search(
            [("state", "not in", ["delivered", "collected", "cancelled"])]
        )
        unpaid = open_jobs.filtered("is_unpaid")
        domain = Domain("id", "in", unpaid.ids)
        return domain if (True in value) == (operator == "in") else ~domain

    @api.depends("state", "promised_on")
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for job in self:
            job.is_overdue = bool(
                job.state not in FINAL_STATES
                and job.state not in ("ready", "out_for_delivery")
                and job.promised_on
                and job.promised_on < now
            )

    def _search_is_overdue(self, operator, value):
        if operator not in ("in", "not in"):
            return NotImplemented
        domain = Domain(
            [
                (
                    "state",
                    "not in",
                    [*FINAL_STATES, "ready", "out_for_delivery"],
                ),
                ("promised_on", "<", fields.Datetime.now()),
            ]
        )
        return domain if (True in value) == (operator == "in") else ~domain

    @api.depends("state", "fulfilment", "item_ids.service_type_id")
    def _compute_next_state(self):
        for job in self:
            job.next_state = job._earlydryer_next_state()

    def _compute_correction_reason(self):
        self.correction_reason = False

    def _inverse_correction_reason(self):
        # only carried to the item write through the context (see write)
        return

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("sale_order_id", "pos_order_id", "earlydryer_branch_id")
    def _check_source_branch(self):
        for job in self:
            source_branch = job._earlydryer_source_branch()
            if source_branch and source_branch != job.earlydryer_branch_id:
                raise ValidationError(
                    self.env._(
                        "Job %(job)s must belong to plant %(branch)s, like its "
                        "source order.",
                        job=job.name,
                        branch=source_branch.display_name,
                    )
                )

    @api.constrains("shelf_id", "earlydryer_branch_id")
    def _check_shelf_branch(self):
        for job in self.filtered("shelf_id"):
            if job.shelf_id.branch_id != job.earlydryer_branch_id:
                raise ValidationError(
                    self.env._(
                        "Shelf %(shelf)s belongs to another plant than job %(job)s.",
                        shelf=job.shelf_id.display_name,
                        job=job.name,
                    )
                )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _earlydryer_is_manager(self):
        return self.env.su or self.env.user.has_group(MANAGER_GROUP)

    @api.model_create_multi
    def create(self, vals_list):
        is_manager = self._earlydryer_is_manager()
        for vals in vals_list:
            if not is_manager:
                if not vals.get("sale_order_id") and not vals.get("pos_order_id"):
                    raise AccessError(
                        self.env._(
                            "Only a Branch Manager can create a laundry job without "
                            "a sales or POS order."
                        )
                    )
                vals["state"] = "received"
        jobs = super().create(vals_list)
        for job in jobs:
            if not job.name or job.name == self.env._("New"):
                sequence = job.earlydryer_branch_id._laundry_job_ensure_sequence()
                job.name = sequence.sudo().next_by_id(
                    sequence_date=fields.Date.to_date(job.received_on)
                )
        self.env["laundry.job.stage.log"].create(
            [
                {
                    "job_id": job.id,
                    "from_state": False,
                    "to_state": job.state,
                    "date": job.received_on,
                    "employee_id": job._earlydryer_default_employee().id,
                }
                for job in jobs
            ]
        )
        return jobs

    def write(self, vals):
        if "state" in vals and not self.env.context.get(MOVE_CTX) and not self.env.su:
            raise UserError(self.env._("Use the stage buttons to move a laundry job."))
        if not self._earlydryer_is_manager():
            if "promised_on" in vals and any(job.state != "received" for job in self):
                raise AccessError(
                    self.env._(
                        "Only a Branch Manager can change the promised date after "
                        "intake."
                    )
                )
            if "shelf_id" in vals and any(
                job.state in ("collected", "delivered") for job in self
            ):
                raise AccessError(
                    self.env._(
                        "Only a Branch Manager can change the shelf of a collected "
                        "or delivered job."
                    )
                )
        reason = vals.pop("correction_reason", False)
        jobs = self.with_context(**{CORRECTION_CTX: reason}) if reason else self
        return super(LaundryJob, jobs).write(vals)

    def unlink(self):
        if not self.env.su and not self.env.user.has_group(
            "earlydryer_base.group_admin"
        ):
            raise AccessError(
                self.env._("Laundry jobs cannot be deleted; cancel them instead.")
            )
        return super().unlink()

    # ------------------------------------------------------------------
    # Creation from orders
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_source_field(self, source):
        """Job field holding ``source`` (a sales or POS order), or False."""
        if not source:
            return False
        return {"sale.order": "sale_order_id", "pos.order": "pos_order_id"}.get(
            source._name, False
        )

    def _earlydryer_source(self):
        self.ensure_one()
        return self.sale_order_id or self.pos_order_id

    def _earlydryer_source_branch(self):
        self.ensure_one()
        if self.sale_order_id:
            return self.sale_order_id.sudo().earlydryer_branch_id
        if self.pos_order_id:
            return self.pos_order_id.sudo().config_id.earlydryer_branch_id
        return self.env["earlydryer.branch"]

    @api.model
    def _earlydryer_catalog_channel(self, channel):
        """Price list channel of the catalogue for a job/order channel."""
        if channel in ("walk_in", "corporate"):
            return channel
        # website, WhatsApp and phone orders are priced like pickups
        return "pickup"

    @api.model
    def _earlydryer_prepare_items(self, lines, source_field=False):
        """Item values of plain ``lines`` (see ``_earlydryer_create_from_lines``)."""
        Product = self.env["product.product"]
        Surcharge = self.env["earlydryer.surcharge"]
        line_field = {"sale_order_id": "sale_line_id", "pos_order_id": "pos_line_id"}
        item_vals = []
        sequence = 10
        for line in lines:
            product = line["product_id"]
            if isinstance(product, int):
                product = Product.browse(product)
            if product.earlydryer_kind != "laundry":
                continue
            quantity = int(float_round(line.get("quantity", 1.0), precision_digits=0))
            pieces = product.earlydryer_garment_category_id.piece_count or 1
            surcharges = line.get("surcharge_ids") or Surcharge
            if not isinstance(surcharges, models.BaseModel):
                surcharges = Surcharge.browse(surcharges)
            for _unit in range(max(quantity, 0)):
                for piece in range(1, pieces + 1):
                    vals = {
                        "sequence": sequence,
                        "product_id": product.id,
                        "piece_index": piece,
                        "piece_count": pieces,
                        # the garment price is carried by its first piece, so
                        # the items add up to the order lines
                        "price_unit": line.get("price_unit", 0.0)
                        if piece == 1
                        else 0.0,
                        "surcharge_ids": [Command.set(surcharges.ids)],
                        "colour": line.get("colour") or False,
                        "brand": line.get("brand") or False,
                        "condition_note": line.get("condition_note") or False,
                    }
                    if source_field and line.get("source_line_id"):
                        vals[line_field[source_field]] = line["source_line_id"]
                    item_vals.append(vals)
                    sequence += 1
        return item_vals

    @api.model
    def _earlydryer_create_from_lines(
        self, partner, branch, channel, fulfilment, express, lines, source=None, **extra
    ):
        """Create the laundry job of an order, once per source.

        :param partner: ``res.partner`` customer
        :param branch: ``earlydryer.branch`` processing the order
        :param channel: one of ``CHANNELS``
        :param fulfilment: ``collect`` or ``deliver``
        :param express: bool
        :param lines: list of plain dicts, one per order line::

            {"product_id": int or product.product,
             "quantity": float,
             "price_unit": float,            # garment unit price at intake
             "surcharge_ids": ids or recordset,
             "colour": str, "brand": str, "condition_note": str,
             "source_line_id": int}          # sale.order.line / pos.order.line

            Lines whose product is not a laundry product are ignored. Each
            unit of quantity becomes ``piece_count`` items.
        :param source: ``sale.order`` or ``pos.order`` record, or None for a
            manual job (Branch Manager only)
        :param extra: other job values (customer_note, received_on...)
        :returns: the job (the existing one when the source already has one),
            or an empty recordset when no line is a laundry line
        """
        source_field = self._earlydryer_source_field(source)
        if source is not None and source and not source_field:
            raise UserError(
                self.env._(
                    "Laundry jobs cannot be created from %(model)s.", model=source._name
                )
            )
        if source_field:
            existing = self.with_context(active_test=False).search(
                [(source_field, "=", source.id)], limit=1
            )
            if existing:
                return existing
        item_vals = self._earlydryer_prepare_items(lines, source_field)
        if not item_vals:
            return self.browse()
        vals = {
            "partner_id": partner.id,
            "earlydryer_branch_id": branch.id,
            "channel": channel,
            "fulfilment": fulfilment,
            "express": bool(express),
            "item_ids": [Command.create(item) for item in item_vals],
            **extra,
        }
        if source_field:
            vals[source_field] = source.id
        return self.create(vals)

    # ------------------------------------------------------------------
    # Amounts and release
    # ------------------------------------------------------------------

    def _earlydryer_amounts(self):
        """``{"total", "paid"}`` of the job from its source record."""
        self.ensure_one()
        if self.sale_order_id:
            return self._earlydryer_sale_amounts()
        if self.pos_order_id:
            return self._earlydryer_pos_amounts()
        return self._earlydryer_manual_amounts()

    def _earlydryer_sale_amounts(self):
        """Total of the sales order; paid = settled part of its posted invoices."""
        self.ensure_one()
        order = self.sale_order_id.sudo()
        paid = 0.0
        for invoice in order.invoice_ids.filtered(lambda m: m.state == "posted"):
            settled = invoice.amount_total - invoice.amount_residual
            paid += -settled if invoice.move_type == "out_refund" else settled
        return {"total": order.amount_total, "paid": paid}

    def _earlydryer_pos_amounts(self):
        """Amounts of a POS order.

        A paid or posted POS order is fully paid, except the part paid with a
        customer-account method (Odoo 19: a method without journal, type
        ``pay_later``), which stays due until the order's invoice is paid. A
        draft order counts its non pay-later payments. earlydryer_pos refines
        this for offline orders.
        """
        self.ensure_one()
        order = self.pos_order_id.sudo()
        total = order.amount_total
        pay_later = sum(
            payment.amount
            for payment in order.payment_ids
            if payment.payment_method_id.type == "pay_later"
        )
        if order.state in ("paid", "done"):
            paid = total - pay_later
            invoice = order.account_move
            if pay_later and invoice and invoice.state == "posted":
                paid += max(pay_later - invoice.amount_residual, 0.0)
        elif order.state == "cancel":
            paid = 0.0
        else:
            paid = sum(order.payment_ids.mapped("amount")) - pay_later
        return {"total": total, "paid": paid}

    def _earlydryer_manual_amounts(self):
        """Manual jobs (corrections, migrated orders) owe nothing here."""
        self.ensure_one()
        return {"total": 0.0, "paid": 0.0}

    def _earlydryer_extra_paid(self):
        """Hook: amounts paid outside the source record (wallet advances...)."""
        self.ensure_one()
        return 0.0

    def _earlydryer_credit_approved(self, amount):
        self.ensure_one()
        return bool(
            self.env["earlydryer.approval.request"]
            .sudo()
            .search_count(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "=", self.id),
                    ("approval_type", "=", "credit"),
                    ("state", "=", "approved"),
                    ("value", ">=", amount),
                ],
                limit=1,
            )
        )

    def _earlydryer_check_release(self):
        """Nothing leaves the plant unpaid unless a manager approved credit."""
        for job in self:
            due = job.amount_due
            if job.currency_id.compare_amounts(due, 0.0) <= 0:
                continue
            if job._earlydryer_approval_rule("credit", due):
                # raises naming the approver group; self-approves when allowed
                job._earlydryer_approval_ensure("credit", due)
                continue
            # no rule matches: credit still needs a Branch Manager
            if job._earlydryer_credit_approved(due):
                continue
            if self.env.user.has_group(MANAGER_GROUP):
                job.message_post(
                    body=self.env._(
                        "Released on credit (%(amount)s due) by %(user)s.",
                        amount=job._earlydryer_format_amount(due),
                        user=self.env.user.name,
                    ),
                    subtype_xmlid="mail.mt_note",
                )
                continue
            raise UserError(
                self.env._(
                    "Job %(job)s still has %(amount)s to pay. Take the payment or "
                    "request a credit approval from a Branch Manager.",
                    job=job.name,
                    amount=job._earlydryer_format_amount(due),
                )
            )
        return True

    def _earlydryer_format_amount(self, amount):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        return f"{currency.symbol or ''}{amount:,.2f}"

    def action_request_credit_approval(self):
        self.ensure_one()
        if self.currency_id.compare_amounts(self.amount_due, 0.0) <= 0:
            raise UserError(self.env._("Nothing is due on %(job)s.", job=self.name))
        return self._earlydryer_approval_wizard_action("credit", self.amount_due)

    def _earlydryer_on_approval_decided(self, request):
        res = super()._earlydryer_on_approval_decided(request)
        if request.approval_type == "credit":
            if request.state == "approved":
                body = self.env._(
                    "Credit of %(amount)s approved: the order can leave the plant "
                    "unpaid.",
                    amount=self._earlydryer_format_amount(request.value),
                )
            else:
                body = self.env._(
                    "Credit refused: the order must be paid before it leaves the plant."
                )
            self.sudo().message_post(body=body, subtype_xmlid="mail.mt_note")
        return res

    # ------------------------------------------------------------------
    # Stage moves
    # ------------------------------------------------------------------

    def _earlydryer_state_label(self, state):
        return dict(self._fields["state"]._description_selection(self.env)).get(
            state, state or ""
        )

    def _earlydryer_next_state(self):
        """Natural next stage, skipping the stages no item's service needs."""
        self.ensure_one()
        state = self.state
        if state == "ready":
            return "out_for_delivery" if self.fulfilment == "deliver" else "collected"
        if state == "out_for_delivery":
            return "delivered"
        if state in FORWARD_PATH:
            services = self.item_ids.service_type_id
            for candidate in FORWARD_PATH[FORWARD_PATH.index(state) + 1 :]:
                if services._uses_stage(candidate):
                    return candidate
        return False

    def _earlydryer_move_kind(self, target):
        """Classify a move of this job to ``target``.

        ``noop`` (already there), ``normal`` (next stage, or a skip of stages
        no item needs), ``skip`` (skips needed stages), ``backward``,
        ``cancel``, ``uncollected`` or ``other`` (any other move).
        """
        self.ensure_one()
        state = self.state
        if target == state:
            return "noop"
        if target == "cancelled":
            return "cancel"
        if state in FORWARD_PATH and target in FORWARD_PATH:
            current, wanted = FORWARD_PATH.index(state), FORWARD_PATH.index(target)
            if wanted < current:
                return "backward"
            services = self.item_ids.service_type_id
            skipped = FORWARD_PATH[current + 1 : wanted]
            if any(services._uses_stage(stage) for stage in skipped):
                return "skip"
            return "normal"
        if state == "ready" and target in RELEASE_STATES:
            return "normal"
        if state == "out_for_delivery" and target == "delivered":
            return "normal"
        if state == "ready" and target == "uncollected":
            return "uncollected"
        if state in FORWARD_PATH and target in (
            "out_for_delivery",
            "delivered",
            "collected",
        ):
            return "skip"
        return "other"

    def _earlydryer_check_move(self, target, kind, employee, note, rework=False):
        """Raise when this job cannot move to ``target`` (``kind`` of move)."""
        self.ensure_one()
        target_label = self._earlydryer_state_label(target)
        is_manager = self._earlydryer_is_manager()
        if self.state == "cancelled":
            raise UserError(self.env._("Job %(job)s is cancelled.", job=self.name))
        if kind == "cancel":
            if not is_manager:
                raise AccessError(
                    self.env._("Only a Branch Manager can cancel a laundry job.")
                )
            if self.state in FINAL_STATES:
                raise UserError(
                    self.env._(
                        "Job %(job)s is closed and cannot be cancelled.", job=self.name
                    )
                )
            if not (note or self.cancel_reason or "").strip():
                raise UserError(
                    self.env._("Give the reason for cancelling %(job)s.", job=self.name)
                )
        elif kind == "uncollected":
            if not self.env.su:
                if not is_manager:
                    raise AccessError(
                        self.env._(
                            "Jobs become Uncollected automatically; only a Branch "
                            "Manager can do it by hand."
                        )
                    )
                if not (note or "").strip():
                    raise UserError(self.env._("Explain why the job is uncollected."))
        elif kind in ("skip", "backward", "other") and not (
            rework and kind == "backward"
        ):
            if not is_manager:
                raise AccessError(
                    self.env._(
                        "Moving job %(job)s from %(from)s to %(to)s is not the normal "
                        "flow: only a Branch Manager can do it.",
                        job=self.name,
                        **{"from": self._earlydryer_state_label(self.state)},
                        to=target_label,
                    )
                )
            if not (note or "").strip():
                raise UserError(
                    self.env._(
                        "Explain why job %(job)s goes from %(from)s to %(to)s.",
                        job=self.name,
                        **{"from": self._earlydryer_state_label(self.state)},
                        to=target_label,
                    )
                )
        if target in PRODUCTION_STATES and not employee:
            raise UserError(
                self.env._(
                    "Record who did the work to move job %(job)s to %(to)s.",
                    job=self.name,
                    to=target_label,
                )
            )
        self._earlydryer_check_gate(target)

    def _earlydryer_check_gate(self, target):
        """Business conditions to enter ``target``."""
        self.ensure_one()
        if target == "tagged" and not self._check_can_tag():
            raise UserError(
                self.env._("Tag every item of job %(job)s first.", job=self.name)
            )
        if target == "packed":
            if self.item_ids.filtered("missing"):
                raise UserError(
                    self.env._(
                        "Job %(job)s has missing items: it cannot be packed.",
                        job=self.name,
                    )
                )
            if self.item_ids.filtered(lambda item: item.qc_state != "passed"):
                raise UserError(
                    self.env._(
                        "Every item of job %(job)s must pass QC before packing.",
                        job=self.name,
                    )
                )
        if target == "ready" and not self.shelf_id:
            raise UserError(
                self.env._(
                    "Put job %(job)s on a shelf before marking it ready.", job=self.name
                )
            )
        if target in RELEASE_STATES:
            self._earlydryer_check_release()

    def _check_can_tag(self):
        """Hook: whether the job can be marked Tagged (earlydryer_tagging checks
        that every item whose service requires a tag has one)."""
        self.ensure_one()
        return True

    def _earlydryer_coerce_employee(self, employee):
        Employee = self.env["hr.employee"]
        if not employee:
            return Employee
        if isinstance(employee, int):
            return Employee.browse(employee)
        return employee

    def _earlydryer_coerce_items(self, items):
        Item = self.env["laundry.job.item"]
        if not items:
            return Item
        if isinstance(items, models.BaseModel):
            return items
        return Item.browse(items)

    def action_move_to(self, target_state, employee=None, items=None, note=None):
        """Move the jobs to ``target_state``: the only way to change stages.

        :param target_state: a job state
        :param employee: ``hr.employee`` (record or id) who did the work;
            required for the production stages
        :param items: ``laundry.job.item`` records (or ids) the move covered;
            empty means the whole job
        :param note: required for backward moves, skips and cancellations
        :returns: True. Jobs already in ``target_state`` are left untouched.
        """
        return self._earlydryer_move(
            target_state, employee=employee, items=items, note=note
        )

    def _earlydryer_move(
        self, target_state, employee=None, items=None, note=None, rework=False
    ):
        if target_state not in dict(STATES):
            raise UserError(self.env._("Unknown stage %(stage)s.", stage=target_state))
        employee = self._earlydryer_coerce_employee(employee)
        items = self._earlydryer_coerce_items(items)
        # the promise is computed at intake only: settle it before leaving
        self.flush_recordset(["promised_on"])
        jobs = self.filtered(lambda job: job.state != target_state)
        kinds = {}
        for job in jobs:
            kinds[job] = job._earlydryer_move_kind(target_state)
            job._earlydryer_check_move(
                target_state, kinds[job], employee, note, rework=rework
            )
        Log = self.env["laundry.job.stage.log"]
        now = fields.Datetime.now()
        for job in jobs:
            old_state = job.state
            vals = {"state": target_state}
            if target_state == "ready":
                vals["ready_on"] = now
                vals["uncollected_reminders_sent"] = False
            if target_state in FINAL_STATES:
                vals["closed_on"] = now
            elif old_state in FINAL_STATES:
                vals["closed_on"] = False
            if target_state == "cancelled" and note:
                vals["cancel_reason"] = note
            job.with_context(**{MOVE_CTX: True}).write(vals)
            job_items = items.filtered(lambda item, job=job: item.job_id == job)
            Log.create(
                {
                    "job_id": job.id,
                    "item_ids": [Command.set(job_items.ids)],
                    "from_state": old_state,
                    "to_state": target_state,
                    "date": now,
                    "employee_id": employee.id,
                    "note": note or False,
                }
            )
            job._earlydryer_post_move_message(old_state, target_state, employee, note)
            if target_state == "cancelled":
                job._earlydryer_notify_source_cancelled()
            job._earlydryer_on_state_changed(old_state, target_state)
        return True

    def _earlydryer_post_move_message(self, old_state, new_state, employee, note):
        """Who did the work and why; the stage change itself is tracked."""
        self.ensure_one()
        if not employee and not note:
            return
        parts = []
        if employee:
            parts.append(
                self.env._(
                    "%(stage)s: work by %(employee)s",
                    stage=self._earlydryer_state_label(new_state),
                    employee=employee.name,
                )
            )
        if note:
            parts.append(note)
        self.message_post(
            body=Markup("<br/>").join(parts), subtype_xmlid="mail.mt_note"
        )

    def _earlydryer_notify_source_cancelled(self):
        """Tell the source order; money matters stay with Finance."""
        self.ensure_one()
        source = self._earlydryer_source()
        if source:
            source.sudo().message_post(
                body=self.env._(
                    "Laundry job %(job)s was cancelled: %(reason)s. The order, "
                    "its invoices and payments are unchanged; Finance decides on "
                    "any refund.",
                    job=self.name,
                    reason=self.cancel_reason or "",
                ),
                subtype_xmlid="mail.mt_note",
            )

    def _earlydryer_on_state_changed(self, old_state, new_state):
        """Hook called after every successful stage move (notifications,
        logistics...)."""
        self.ensure_one()
        return

    # ------------------------------------------------------------------
    # QC
    # ------------------------------------------------------------------

    def _earlydryer_check_qc(self, employee):
        self.ensure_one()
        if self.state != "qc":
            raise UserError(self.env._("Job %(job)s is not in QC.", job=self.name))
        if not employee:
            raise UserError(self.env._("Record who did the quality check."))

    def action_qc_pass(self, items=None, employee=None):
        """Pass ``items`` (default: the items not passed yet) at QC."""
        self.ensure_one()
        employee = self._earlydryer_coerce_employee(employee)
        self._earlydryer_check_qc(employee)
        items = self._earlydryer_coerce_items(items) or self.item_ids.filtered(
            lambda item: item.qc_state != "passed"
        )
        items = items.filtered(lambda item: item.job_id == self)
        items.write(
            {
                "qc_state": "passed",
                "qc_employee_id": employee.id,
                "qc_date": fields.Datetime.now(),
            }
        )
        self.message_post(
            body=self.env._(
                "QC passed by %(employee)s: %(items)s",
                employee=employee.name,
                items=", ".join(items.mapped("display_name")),
            ),
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_qc_fail(self, items, employee, return_to_state, note):
        """Send ``items`` back for rework: the job returns to ``return_to_state``."""
        self.ensure_one()
        employee = self._earlydryer_coerce_employee(employee)
        items = self._earlydryer_coerce_items(items).filtered(
            lambda item: item.job_id == self
        )
        self._earlydryer_check_qc(employee)
        if not items:
            raise UserError(self.env._("Select the items that failed QC."))
        if return_to_state not in REWORK_STATES:
            raise UserError(
                self.env._("Failed items go back to Sorted, Washed or Ironed.")
            )
        if not (note or "").strip():
            raise UserError(self.env._("Describe why the items failed QC."))
        for item in items:
            item.write(
                {
                    "qc_state": "rework",
                    "rework_count": item.rework_count + 1,
                    "qc_employee_id": employee.id,
                    "qc_date": fields.Datetime.now(),
                }
            )
        return self._earlydryer_move(
            return_to_state, employee=employee, items=items, note=note, rework=True
        )

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def _earlydryer_default_employee(self):
        """The current user's employee when they work on this job's plant."""
        employee = self.env.user.sudo().employee_id
        if not employee:
            return self.env["hr.employee"]
        if len(self) == 1 and employee.earlydryer_branch_id not in (
            self.earlydryer_branch_id,
            self.env["earlydryer.branch"],
        ):
            return self.env["hr.employee"]
        return self.env["hr.employee"].browse(employee.id)

    def _earlydryer_move_wizard_action(self, target_state, title=None):
        return {
            "type": "ir.actions.act_window",
            "name": title or self.env._("Move to Stage"),
            "res_model": "laundry.job.move.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_job_ids": self.ids,
                "default_target_state": target_state,
            },
        }

    def action_open_move_wizard(self):
        """Header button: move to the next stage, recording who did the work."""
        target = (
            self[:1].next_state if len(set(self.mapped("next_state"))) == 1 else False
        )
        return self._earlydryer_move_wizard_action(target)

    def action_next_stage(self):
        """Plain next-stage button: moves at once unless an employee is needed."""
        self.ensure_one()
        target = self._earlydryer_next_state()
        if not target:
            raise UserError(self.env._("Job %(job)s has no next stage.", job=self.name))
        if target in PRODUCTION_STATES:
            return self._earlydryer_move_wizard_action(target)
        employee = self._earlydryer_default_employee()
        self.action_move_to(target, employee=employee)
        return True

    def action_collect(self):
        self.action_move_to("collected", employee=self._earlydryer_default_employee())
        return True

    def action_out_for_delivery(self):
        self.action_move_to(
            "out_for_delivery", employee=self._earlydryer_default_employee()
        )
        return True

    def action_delivered(self):
        self.action_move_to("delivered", employee=self._earlydryer_default_employee())
        return True

    def action_open_cancel_wizard(self):
        return self._earlydryer_move_wizard_action(
            "cancelled", self.env._("Cancel Job")
        )

    def action_open_qc_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Quality Check"),
            "res_model": "laundry.job.qc.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_job_id": self.id},
        }

    def _earlydryer_request_wizard_action(self, request_type):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Customer Request"),
            "res_model": "laundry.job.request.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_job_id": self.id,
                "default_request_type": request_type,
            },
        }

    def action_customer_change_request(self):
        return self._earlydryer_request_wizard_action("change")

    def action_customer_cancel_request(self):
        return self._earlydryer_request_wizard_action("cancel")

    def action_view_source(self):
        self.ensure_one()
        source = self._earlydryer_source()
        if not source:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": source._name,
            "res_id": source.id,
            "view_mode": "form",
        }

    # ------------------------------------------------------------------
    # Customer requests
    # ------------------------------------------------------------------

    def _earlydryer_request_users(self):
        """The branch manager, or the Branch Managers allowed on the plant."""
        self.ensure_one()
        branch = self.earlydryer_branch_id.sudo()
        if branch.manager_id and branch.manager_id.active:
            return branch.manager_id
        group = self.env.ref(MANAGER_GROUP).sudo()
        return group.all_user_ids.filtered(
            lambda user: (
                user.active and not user.share and branch in user.earlydryer_branch_ids
            )
        )

    def _earlydryer_customer_request(self, request_type, description):
        """Schedule a To Do for the branch manager and log the request."""
        self.ensure_one()
        if not (description or "").strip():
            raise UserError(self.env._("Describe what the customer asked for."))
        if request_type == "cancel":
            summary = self.env._("Customer asks to cancel %(job)s", job=self.name)
        else:
            summary = self.env._("Customer asks to change %(job)s", job=self.name)
        users = self._earlydryer_request_users()
        for user in users:
            self.activity_schedule(
                TODO_ACTIVITY, summary=summary, note=description, user_id=user.id
            )
        if not users:
            _logger.warning(
                "No Branch Manager found for plant %s: request on %s not assigned.",
                self.earlydryer_branch_id.display_name,
                self.name,
            )
        self.message_post(
            body=Markup("<b>%s</b><br/>%s") % (summary, description),
            subtype_xmlid="mail.mt_note",
        )
        return True

    # ------------------------------------------------------------------
    # Uncollected orders
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_parse_reminder_days(self, value, strict=False):
        days = set()
        for part in (value or "").split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit() or int(part) < 1:
                if strict:
                    raise ValidationError(
                        self.env._(
                            "Reminder days must be positive whole numbers separated "
                            "by commas, e.g. 3,7,12."
                        )
                    )
                continue
            days.add(int(part))
        return sorted(days)

    @api.model
    def _earlydryer_uncollected_settings(self):
        params = self.env["ir.config_parameter"].sudo()
        limit = params.get_param("earlydryer.uncollected_days", "14")
        limit = int(limit) if str(limit).strip().isdigit() else 14
        reminders = self._earlydryer_parse_reminder_days(
            params.get_param("earlydryer.uncollected_reminder_days", "3,7,12")
        )
        return limit, [day for day in reminders if day < limit]

    def _earlydryer_reminders_sent(self):
        self.ensure_one()
        return set(
            self._earlydryer_parse_reminder_days(self.uncollected_reminders_sent)
        )

    def _earlydryer_send_uncollected_reminder(self, day):
        """Hook: remind the customer to collect (earlydryer_notifications sends
        WhatsApp/SMS). Called once per reminder day."""
        self.ensure_one()
        self.message_post(
            body=self.env._("Collection reminder (day %(day)s after ready).", day=day),
            subtype_xmlid="mail.mt_note",
        )

    @api.model
    def _cron_earlydryer_uncollected(self):
        """Daily: remind customers, then mark old ready orders Uncollected."""
        jobs = self.sudo().search(
            [
                ("state", "=", "ready"),
                ("fulfilment", "=", "collect"),
                ("ready_on", "!=", False),
            ]
        )
        limit, reminder_days = self._earlydryer_uncollected_settings()
        now = fields.Datetime.now()
        for job in jobs:
            age = (now - job.ready_on).days
            if age >= limit:
                job.action_move_to(
                    "uncollected",
                    note=self.env._(
                        "Not collected within %(days)s days of being ready: "
                        "Earlydryer's liability ends.",
                        days=limit,
                    ),
                )
                continue
            sent = job._earlydryer_reminders_sent()
            due = [day for day in reminder_days if day <= age and day not in sent]
            if not due:
                continue
            # a missed run only sends the latest reminder
            job._earlydryer_send_uncollected_reminder(due[-1])
            sent.update(due)
            job.uncollected_reminders_sent = ",".join(str(day) for day in sorted(sent))
        return True

    # ------------------------------------------------------------------
    # Demo data
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_load_demo_jobs(self):
        """Demo only: confirmed sales orders on both plants, moved to various
        stages with the employees who did the work."""
        ref = self.env.ref
        catalog = self.env["earlydryer.catalog"]

        def product(category, service):
            return catalog.get_laundry_product(
                ref(f"earlydryer_service_catalog.garment_category_{category}"),
                ref(f"earlydryer_service_catalog.service_type_{service}"),
            )

        def employee(xmlid):
            return ref(f"earlydryer_laundry_order.employee_{xmlid}")

        def order(partner, branch, channel, fulfilment, lines, express=False):
            sale = self.env["sale.order"].create(
                {
                    "partner_id": ref(partner).id,
                    "earlydryer_branch_id": ref(f"earlydryer_base.branch_{branch}").id,
                    "earlydryer_channel": channel,
                    "earlydryer_fulfilment": fulfilment,
                    "earlydryer_express": express,
                    "order_line": [
                        Command.create(
                            {
                                "product_id": prod.id,
                                "product_uom_qty": qty,
                                "earlydryer_surcharge_ids": [
                                    Command.set(surcharges.ids)
                                ],
                                "earlydryer_colour": colour,
                            }
                        )
                        for prod, qty, surcharges, colour in lines
                    ],
                }
            )
            sale.action_earlydryer_apply_extras()
            sale.action_confirm()
            return sale.laundry_job_ids

        def walk(job, steps):
            for state, who in steps:
                if state == "qc_pass":
                    job.action_qc_pass(employee=employee(who))
                    continue
                if state == "ready":
                    job.shelf_id = job.earlydryer_branch_id.shelf_ids[:1]
                job.action_move_to(state, employee=employee(who) if who else None)

        no_surcharge = self.env["earlydryer.surcharge"]
        beads = ref("earlydryer_service_catalog.surcharge_beads")
        lace = ref("earlydryer_service_catalog.surcharge_lace")
        to_washed = [
            ("tagged", "front_desk_p1"),
            ("sorted", "production_p1"),
            ("washed", "washer_p1"),
        ]
        # Plant 1, pickup to deliver: just received
        order(
            "earlydryer_laundry_order.partner_customer_adaeze",
            "plant_1",
            "pickup",
            "deliver",
            [
                (product("shirt", "wash_iron"), 4, no_surcharge, "White"),
                (product("trouser", "wash_iron"), 2, no_surcharge, "Navy"),
            ],
        )
        # Plant 1, phone order: washed
        job = order(
            "earlydryer_laundry_order.partner_customer_kabir",
            "plant_1",
            "phone",
            "collect",
            [(product("suit", "dry_cleaning"), 1, no_surcharge, "Charcoal")],
        )
        walk(job, to_washed)
        # Plant 2, WhatsApp, express: ironed
        job = order(
            "earlydryer_laundry_order.partner_customer_funmi",
            "plant_2",
            "whatsapp",
            "collect",
            [(product("gown", "dry_cleaning"), 1, lace, "Gold")],
            express=True,
        )
        walk(
            job,
            [
                ("tagged", "qc_p2"),
                ("sorted", "washer_p2"),
                ("washed", "washer_p2"),
                ("dried", "washer_p2"),
                ("ironed", "ironer_p2"),
            ],
        )
        # Plant 1, website: ready on shelf, unpaid
        job = order(
            "earlydryer_laundry_order.partner_customer_samuel",
            "plant_1",
            "website",
            "collect",
            [(product("agbada", "dry_cleaning"), 1, beads, "Cream")],
        )
        walk(
            job,
            to_washed
            + [
                ("dried", "washer_p1"),
                ("ironed", "ironer_p1"),
                ("qc", "qc_p1"),
                ("qc_pass", "qc_p1"),
                ("packed", "front_desk_p1"),
                ("ready", "front_desk_p1"),
            ],
        )
        # Plant 2, corporate client: overdue at sorting
        job = order(
            "earlydryer_service_catalog.partner_corporate_client",
            "plant_2",
            "corporate",
            "deliver",
            [(product("bed_sheet", "wash_iron"), 6, no_surcharge, "White")],
        )
        job.write(
            {"received_on": fields.Datetime.subtract(fields.Datetime.now(), days=6)}
        )
        walk(job, [("tagged", None), ("sorted", "washer_p2")])
        job.promised_on = fields.Datetime.subtract(fields.Datetime.now(), days=2)
        return True
