# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import binascii
import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.earlydryer_base.models.earlydryer_approval_request import (
    INTERNAL_CTX,
)
from odoo.addons.earlydryer_laundry_order.models.laundry_job import FULFILMENTS

_logger = logging.getLogger(__name__)

TODO_ACTIVITY = "mail.mail_activity_data_todo"
# context key: POS jobs keep the codes printed at the till; no server codes
NO_AUTO_TAG_CTX = "earlydryer_pos_no_auto_tag"
# photos of one garment line, compressed on the till (about 150 KB each)
MAX_PHOTO_BYTES = 3 * 1024 * 1024
MAX_PHOTOS_PER_LINE = 12


class PosOrder(models.Model):
    _name = "pos.order"
    _inherit = ["pos.order", "mail.activity.mixin"]

    earlydryer_express = fields.Boolean(string="Express")
    earlydryer_fulfilment = fields.Selection(
        FULFILMENTS, string="Fulfilment", default="collect"
    )
    earlydryer_customer_note = fields.Text(
        string="Laundry Instructions", help='Customer instructions such as "no starch".'
    )
    earlydryer_new_partner_name = fields.Char(
        string="New Customer Name",
        help="Customer created at the till while offline: matched by phone or "
        "created when the order syncs.",
    )
    earlydryer_new_partner_phone = fields.Char(string="New Customer Phone")
    earlydryer_promised_estimate = fields.Datetime(
        string="Promise Estimated at the Till",
        readonly=True,
        help="Estimate printed on the receipt. The laundry job computes its "
        "own promise from the intake time.",
    )
    earlydryer_job_id = fields.Many2one(
        "laundry.job",
        string="Laundry Job",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
    earlydryer_job_state = fields.Selection(
        related="earlydryer_job_id.state", string="Job Stage"
    )
    earlydryer_job_error = fields.Text(
        string="Job Creation Error",
        readonly=True,
        copy=False,
        help="Set when the laundry job could not be created at sync; a retry is "
        "queued. The sale itself is saved.",
    )
    earlydryer_settlement_job_ids = fields.Many2many(
        "laundry.job",
        "earlydryer_pos_order_settlement_job_rel",
        "order_id",
        "job_id",
        string="Settled Jobs",
        readonly=True,
        copy=False,
        help="Jobs whose balance this order pays.",
    )
    earlydryer_is_laundry = fields.Boolean(
        string="Laundry Order",
        compute="_compute_earlydryer_is_laundry",
        store=True,
    )

    @api.depends("lines.product_id")
    def _compute_earlydryer_is_laundry(self):
        for order in self:
            order.earlydryer_is_laundry = any(
                line.product_id.earlydryer_kind == "laundry" for line in order.lines
            )

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    @api.model
    def _process_order(self, order, existing_order):
        if not order.get("partner_id") and order.get("earlydryer_new_partner_phone"):
            partner = self._earlydryer_offline_partner(
                order.get("earlydryer_new_partner_name"),
                order["earlydryer_new_partner_phone"],
            )
            if partner:
                order["partner_id"] = partner.id
        return super()._process_order(order, existing_order)

    @api.model
    def _earlydryer_offline_partner(self, name, phone):
        """Customer quick-created offline: the contact with that phone, or a
        new one (phone in international form, see the till)."""
        phone = (phone or "").strip()
        if not phone:
            return self.env["res.partner"]
        Partner = self.env["res.partner"].sudo()
        digits = "".join(char for char in phone if char.isdigit())
        partner = (
            Partner.search([("phone", "ilike", digits[-10:])], order="id", limit=1)
            if len(digits) >= 10
            else Partner
        )
        if partner:
            return partner
        return Partner.create({"name": (name or "").strip() or phone, "phone": phone})

    def _process_saved_order(self, draft):
        res = super()._process_saved_order(draft)
        if (
            not draft
            and self.state in ("paid", "done")
            and self.config_id.earlydryer_enabled
        ):
            self._earlydryer_after_sync()
        return res

    def _earlydryer_after_sync(self):
        """Link the lines, settlements and laundry job of a synced order.

        Never raises: a failed job creation is stored, notified and retried.
        """
        self.ensure_one()
        self.lines._earlydryer_resolve_parent_lines()
        self._earlydryer_link_settlements()
        if self.earlydryer_is_laundry and not self.earlydryer_job_id:
            self._earlydryer_sync_job()
        return True

    def _earlydryer_link_settlements(self):
        self.ensure_one()
        Job = self.env["laundry.job"].sudo()
        for line in self.lines.filtered("earlydryer_settlement_job_ref"):
            ref = line.earlydryer_settlement_job_ref
            job = Job.browse(int(ref)).exists() if ref.isdigit() else Job
            if not job:
                job = Job.search([("name", "=", ref)], limit=1)
            if job:
                line.earlydryer_settlement_job_id = job
        self.earlydryer_settlement_job_ids = self.lines.earlydryer_settlement_job_id

    def _earlydryer_sync_job(self, enqueue=True):
        """Steps of the job creation in a savepoint.

        :returns: True when the job exists afterwards
        """
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self._earlydryer_create_job()
        except Exception as error:  # pylint: disable=broad-except
            # never lose the sale: keep the order, log, notify and retry
            _logger.exception("Laundry job creation failed for POS order %s", self.name)
            self._earlydryer_job_failed(error, enqueue=enqueue)
            return False
        if self.earlydryer_job_error:
            self.earlydryer_job_error = False
        return True

    def _earlydryer_job_failed(self, error, enqueue=True):
        self.ensure_one()
        message = str(error) or error.__class__.__name__
        self.sudo().earlydryer_job_error = message
        self.sudo().message_post(
            body=self.env._(
                "The laundry job could not be created: %(error)s. A retry is "
                "queued; use Retry Job Creation once the cause is fixed.",
                error=message,
            ),
            subtype_xmlid="mail.mt_note",
        )
        for user in self.config_id._earlydryer_manager_users():
            self.sudo().activity_schedule(
                TODO_ACTIVITY,
                summary=self.env._(
                    "Laundry job missing for %(order)s", order=self.name
                ),
                note=message,
                user_id=user.id,
            )
        if enqueue:
            self.sudo().with_delay(
                description=self.env._("Create laundry job of %s", self.name),
                max_retries=8,
            )._earlydryer_create_job_from_pos()

    def _earlydryer_create_job_from_pos(self):
        """Queued retry (and button): idempotent, like the job creation."""
        for order in self:
            if order.earlydryer_job_id:
                continue
            if not order._earlydryer_sync_job(enqueue=False):
                raise UserError(
                    self.env._(
                        "Laundry job of %(order)s still not created: %(error)s",
                        order=order.name,
                        error=order.earlydryer_job_error,
                    )
                )
        return True

    def action_earlydryer_retry_job(self):
        self._earlydryer_create_job_from_pos()
        return True

    # ------------------------------------------------------------------
    # Job creation
    # ------------------------------------------------------------------

    def _earlydryer_garment_lines(self):
        self.ensure_one()
        return self.lines.filtered(
            lambda line: line.product_id.earlydryer_kind == "laundry" and line.qty > 0
        )

    def _earlydryer_job_line_vals(self, line):
        """Plain line dict for ``laundry.job._earlydryer_create_from_lines``."""
        surcharges = line.earlydryer_child_line_ids.earlydryer_surcharge_id
        return {
            "product_id": line.product_id.id,
            "quantity": line.qty,
            "price_unit": line.price_unit * (1.0 - (line.discount or 0.0) / 100.0),
            "surcharge_ids": surcharges.ids,
            "colour": line.earlydryer_colour or False,
            "brand": line.earlydryer_brand or False,
            "condition_note": line.earlydryer_condition_note or False,
            "source_line_id": line.id,
        }

    def _earlydryer_create_job(self):
        """Create the laundry job of this order (idempotent), its tags and
        discount logs. Raises on failure (the caller holds the savepoint)."""
        self.ensure_one()
        Job = self.env["laundry.job"].sudo().with_context(**{NO_AUTO_TAG_CTX: True})
        garment_lines = self._earlydryer_garment_lines()
        if not garment_lines:
            return Job.browse()
        branch = self.config_id.earlydryer_branch_id
        if not branch:
            raise UserError(
                self.env._(
                    "Point of sale %(pos)s has no plant.", pos=self.config_id.name
                )
            )
        partner = self.partner_id
        walk_in = self.config_id.earlydryer_walkin_partner_id
        if not partner or partner == walk_in:
            raise UserError(
                self.env._(
                    "Order %(order)s has laundry lines but no identified customer.",
                    order=self.name,
                )
            )
        job = Job._earlydryer_create_from_lines(
            partner,
            branch,
            "walk_in",
            self.earlydryer_fulfilment or "collect",
            self.earlydryer_express,
            [self._earlydryer_job_line_vals(line) for line in garment_lines],
            source=self,
            # offline orders keep their real intake time
            received_on=self.date_order,
            customer_note=self.earlydryer_customer_note or False,
        )
        self.earlydryer_job_id = job
        job._earlydryer_pos_apply_tags(garment_lines, self.employee_id)
        self._earlydryer_log_discount_approvals()
        return job

    def _earlydryer_log_discount_approvals(self):
        """Approved requests (and PIN logs) for the discounts granted at the
        till. Idempotent per rule, approver and value."""
        self.ensure_one()
        Request = self.env["earlydryer.approval.request"].sudo()
        PinLog = self.env["earlydryer.pos.pin.approval"].sudo()
        branch = self.config_id.earlydryer_branch_id
        seen = set()
        for line in self.lines.filtered(
            lambda line: line.earlydryer_discount_rule_id and line.discount > 0
        ):
            rule = line.earlydryer_discount_rule_id
            approver = line.earlydryer_discount_approver_employee_id
            key = (rule.id, approver.id, line.discount)
            if key in seen:
                continue
            seen.add(key)
            exists = Request.search_count(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "=", self.id),
                    ("rule_id", "=", rule.id),
                    ("state", "=", "approved"),
                    ("value", ">=", line.discount),
                ],
                limit=1,
            )
            if exists:
                continue
            decided_by = approver.user_id or self.user_id
            request = Request.with_context(**{INTERNAL_CTX: True}).create(
                {
                    "rule_id": rule.id,
                    "res_model": self._name,
                    "res_id": self.id,
                    "earlydryer_branch_id": branch.id,
                    "company_id": self.company_id.id,
                    "value": line.discount,
                    "reason": self.env._(
                        "Discount approved at till %(pos)s by %(employee)s (PIN).",
                        pos=self.config_id.name,
                        employee=approver.name or decided_by.name,
                    ),
                    "state": "approved",
                    "requested_by_id": self.user_id.id or self.env.uid,
                    "requested_on": self.date_order,
                    "decided_by_id": decided_by.id,
                    "decided_on": self.date_order,
                }
            )
            PinLog.create(
                {
                    "approval_type": "discount",
                    "employee_id": approver.id,
                    "user_id": decided_by.id,
                    "cashier_employee_id": self.employee_id.id,
                    "pos_config_id": self.config_id.id,
                    "pos_order_id": self.id,
                    "rule_id": rule.id,
                    "request_id": request.id,
                    "value": line.discount,
                    "date": self.date_order,
                }
            )
        return True

    # ------------------------------------------------------------------
    # Amounts
    # ------------------------------------------------------------------

    def _earlydryer_pay_later_amount(self):
        self.ensure_one()
        return sum(
            payment.amount
            for payment in self.payment_ids
            if payment.payment_method_id.type == "pay_later"
        )

    def _earlydryer_pay_later_due(self):
        """Open part of this order's Customer Account payments.

        Invoiced: the invoice residual. Session closed: the residual of the
        customer's pay-later receivable lines of the session entry, paid
        oldest order first. Not accounted yet: the whole pay-later amount.
        """
        self.ensure_one()
        order = self.sudo()
        pay_later = order._earlydryer_pay_later_amount()
        if order.currency_id.is_zero(pay_later):
            return 0.0
        invoice = order.account_move
        if invoice and invoice.state == "posted":
            return min(pay_later, invoice.amount_residual)
        move = order.session_move_id
        if not move or move.state != "posted":
            return pay_later
        partner = order.partner_id.commercial_partner_id
        siblings = order.session_id.order_ids.filtered(
            lambda other: other.partner_id.commercial_partner_id == partner
            and not other.account_move
            and other.state in ("paid", "done")
        ).sorted(lambda other: (other.date_order, other.id))
        residual = sum(
            siblings[:1]._earlydryer_receivable_lines().mapped("amount_residual")
        )
        amounts = [(other, other._earlydryer_pay_later_amount()) for other in siblings]
        paid = sum(amount for _other, amount in amounts) - residual
        cumulated = 0.0
        for other, amount in amounts:
            cumulated += amount
            if other == order:
                return min(max(cumulated - paid, 0.0), amount)
        return pay_later

    def _earlydryer_settlement_amount(self):
        """Balance settlement lines of this order (not part of any job)."""
        self.ensure_one()
        return sum(
            self.lines.filtered(
                lambda line: line.product_id.earlydryer_kind == "settlement"
            ).mapped("price_subtotal_incl")
        )

    def _earlydryer_receivable_lines(self):
        """Open customer receivable lines created for these orders' unpaid
        part: invoice receivables, or the per-customer pay-later lines of the
        session entry."""
        lines = self.env["account.move.line"]
        for order in self.sudo():
            partner = order.partner_id.commercial_partner_id
            if order.account_move and order.account_move.state == "posted":
                lines |= order.account_move.line_ids.filtered(
                    lambda line: line.account_id.account_type == "asset_receivable"
                )
            elif order.session_move_id and order.session_move_id.state == "posted":
                lines |= order.session_move_id.line_ids.filtered(
                    lambda line, partner=partner: line.partner_id == partner
                    and line.account_id == partner.property_account_receivable_id
                    and line.balance > 0
                    and not line.earlydryer_settlement
                )
        return lines

    # ------------------------------------------------------------------
    # Photos
    # ------------------------------------------------------------------

    @api.model
    def earlydryer_upload_photo(
        self, order_uuid, line_uuid, index, data, mimetype=None
    ):
        """Attach a condition photo taken at the till to the job items.

        Idempotent per (order, line, index). Called after the order synced.
        :returns: ``{"status": "done"|"pending", "attachment_id"}``; pending
            when the order or its job does not exist yet (the till retries)
        """
        order = self.search([("uuid", "=", order_uuid)], limit=1)
        if not order:
            return {"status": "pending", "reason": "order"}
        order._earlydryer_check_till_user()
        line = order.lines.filtered(lambda line: line.uuid == line_uuid)[:1]
        if not line:
            raise ValidationError(
                self.env._(
                    "Line %(line)s is not on order %(order)s.",
                    line=line_uuid,
                    order=order.name,
                )
            )
        index = int(index)
        if not 0 <= index < MAX_PHOTOS_PER_LINE:
            raise ValidationError(self.env._("Too many photos for one line."))
        Photo = self.env["earlydryer.pos.photo"].sudo()
        photo = Photo.search(
            [
                ("order_uuid", "=", order_uuid),
                ("line_uuid", "=", line_uuid),
                ("index", "=", index),
            ],
            limit=1,
        )
        if photo:
            photo._earlydryer_attach_to_items()
            return {"status": "done", "attachment_id": photo.attachment_id.id}
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValidationError(
                self.env._("The photo is not valid base64.")
            ) from error
        if len(raw) > MAX_PHOTO_BYTES:
            raise ValidationError(self.env._("The photo is too large."))
        if not order.earlydryer_job_id:
            return {"status": "pending", "reason": "job"}
        job_name = order.earlydryer_job_id.name.replace("/", "-")
        attachment = (
            self.env["ir.attachment"]
            .sudo()
            .create(
                {
                    "name": f"{job_name}-{line.id}-{index + 1}.jpg",
                    "raw": raw,
                    "mimetype": mimetype or "image/jpeg",
                    "res_model": "laundry.job",
                    "res_id": order.earlydryer_job_id.id,
                }
            )
        )
        photo = Photo.create(
            {
                "order_uuid": order_uuid,
                "line_uuid": line_uuid,
                "index": index,
                "pos_order_id": order.id,
                "pos_line_id": line.id,
                "attachment_id": attachment.id,
            }
        )
        photo._earlydryer_attach_to_items()
        return {"status": "done", "attachment_id": attachment.id}

    def _earlydryer_check_till_user(self):
        """The user works on this order's plant and has a session open there."""
        self.ensure_one()
        config = self.sudo().config_id
        branch = config.earlydryer_branch_id
        if self.env.su:
            return True
        if not branch or branch not in self.env.user._earlydryer_allowed_branches():
            raise AccessError(self.env._("This order belongs to another plant."))
        open_session = (
            self.env["pos.session"]
            .sudo()
            .search_count(
                [
                    ("state", "in", ("opened", "closing_control")),
                    ("config_id.earlydryer_branch_id", "=", branch.id),
                ],
                limit=1,
            )
        )
        if not open_session:
            raise AccessError(
                self.env._(
                    "No session is open on a till of plant %(branch)s.",
                    branch=branch.display_name,
                )
            )
        return True
