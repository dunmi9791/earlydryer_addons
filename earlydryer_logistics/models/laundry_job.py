# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

from .earlydryer_logistics_stop import (
    ACTIVE_STATES,
    CLOSED_STATES,
    FAILED_CTX,
    GROUPS,
    STOP_CTX,
    TODO_ACTIVITY,
)


class LaundryJob(models.Model):
    _inherit = "laundry.job"

    earlydryer_stop_ids = fields.Many2many(
        "earlydryer.logistics.stop",
        "earlydryer_logistics_stop_job_rel",
        "job_id",
        "stop_id",
        string="Pickups and Deliveries",
        readonly=True,
    )
    earlydryer_stop_count = fields.Integer(
        string="Stops", compute="_compute_earlydryer_stop_count"
    )
    earlydryer_fee_invoice_ids = fields.One2many(
        "account.move",
        "earlydryer_logistics_job_id",
        string="Logistics Fee Invoices",
        readonly=True,
    )

    def _compute_earlydryer_stop_count(self):
        for job in self:
            job.earlydryer_stop_count = len(job.earlydryer_stop_ids)

    # ------------------------------------------------------------------
    # Amounts: fee invoices and door payments
    # ------------------------------------------------------------------

    def _earlydryer_fee_invoices(self):
        """Posted fee invoices of this job (POS / invoiced jobs: a fee on a
        still-open sales order is a line of that order instead)."""
        self.ensure_one()
        return self.sudo().earlydryer_fee_invoice_ids.filtered(
            lambda move: move.state == "posted" and move.move_type == "out_invoice"
        )

    def _earlydryer_amounts(self):
        """Source amounts plus the job's fee invoices, counted once."""
        amounts = dict(super()._earlydryer_amounts())
        for invoice in self._earlydryer_fee_invoices():
            amounts["total"] += invoice.amount_total
            amounts["paid"] += invoice.amount_total - invoice.amount_residual
        return amounts

    def _earlydryer_extra_paid(self):
        """Door payments not matched yet (POS session still open, sales order
        not invoiced): their open receivable credit counts as paid until a
        reconciliation lowers the receivable itself."""
        paid = super()._earlydryer_extra_paid()
        stops = self.env["earlydryer.logistics.stop"].sudo().search(
            [("job_id", "=", self.id), ("cod_payment_id", "!=", False)]
        )
        for stop in stops:
            paid -= sum(stop._earlydryer_cod_credit_lines().mapped("amount_residual"))
        return paid

    # ------------------------------------------------------------------
    # Release: cash on delivery
    # ------------------------------------------------------------------

    def _earlydryer_active_delivery(self):
        self.ensure_one()
        return self.env["earlydryer.logistics.stop"].sudo().search(
            [
                ("stop_type", "=", "delivery"),
                ("job_id", "=", self.id),
                ("state", "in", ACTIVE_STATES),
            ],
            limit=1,
        )

    def _earlydryer_cod_covers(self):
        """The due amount is fully covered by the cash to collect on an
        assigned delivery stop: the controlled exception to the release rule."""
        self.ensure_one()
        due = self.amount_due
        currency = self.currency_id or self.env.company.currency_id
        if currency.compare_amounts(due, 0.0) <= 0:
            return False
        stop = self._earlydryer_active_delivery()
        return bool(
            stop
            and stop._earlydryer_cod_allowed()
            and currency.compare_amounts(stop.cod_amount, due) >= 0
        )

    def _earlydryer_check_release(self):
        covered = self.filtered(lambda job: job._earlydryer_cod_covers())
        for job in covered:
            stop = job._earlydryer_active_delivery()
            job.sudo().message_post(
                body=self.env._(
                    "Released for delivery %(stop)s: %(amount)s to collect at the "
                    "door.",
                    stop=stop.name,
                    amount=job._earlydryer_format_amount(stop.cod_amount),
                ),
                subtype_xmlid="mail.mt_note",
            )
        return super(LaundryJob, self - covered)._earlydryer_check_release()

    # ------------------------------------------------------------------
    # Pickups priced at the plant
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_create_from_lines(
        self, partner, branch, channel, fulfilment, express, lines, source=None, **extra
    ):
        stop = (
            source.sudo().earlydryer_pickup_stop_id
            if source and "earlydryer_pickup_stop_id" in source._fields
            else self.env["earlydryer.logistics.stop"]
        )
        if stop:
            channel = "pickup"
            # intake time: when the bags reached the plant
            extra["received_on"] = (
                stop.plant_arrival_on or stop.done_on or extra.get("received_on")
            )
            if stop.return_delivery:
                fulfilment = "deliver"
            if stop.customer_note and not extra.get("customer_note"):
                extra["customer_note"] = stop.customer_note
        job = super()._earlydryer_create_from_lines(
            partner, branch, channel, fulfilment, express, lines, source=source, **extra
        )
        if stop and job and stop.job_id != job:
            stop._earlydryer_link_job(job, source)
        return job

    # ------------------------------------------------------------------
    # Ready to deliver
    # ------------------------------------------------------------------

    def _earlydryer_on_state_changed(self, old_state, new_state):
        res = super()._earlydryer_on_state_changed(old_state, new_state)
        if (
            new_state == "ready"
            and self.fulfilment == "deliver"
            and not self.env.context.get(FAILED_CTX)
        ):
            self._earlydryer_logistics_ready()
        return res

    def _earlydryer_delivery_address(self):
        """Return address: the pickup's, else the order's delivery address."""
        self.ensure_one()
        pickup = self.env["earlydryer.logistics.stop"].sudo().search(
            [("stop_type", "=", "pickup"), ("job_ids", "in", self.ids)],
            order="id desc",
            limit=1,
        )
        if pickup:
            return pickup._earlydryer_return_address()
        order = self.sudo().sale_order_id
        return order.partner_shipping_id if order else self.partner_id

    def _earlydryer_logistics_ready(self):
        self.ensure_one()
        Stop = self.env["earlydryer.logistics.stop"].sudo()
        open_stop = Stop.search(
            [
                ("stop_type", "=", "delivery"),
                ("job_id", "=", self.id),
                ("state", "not in", CLOSED_STATES),
            ],
            limit=1,
        )
        if open_stop:
            return open_stop
        branch = self.earlydryer_branch_id.sudo()
        if branch.earlydryer_auto_draft_delivery:
            stop = Stop.with_context(**{STOP_CTX: True}).create(
                {
                    "stop_type": "delivery",
                    "partner_id": self.partner_id.id,
                    "address_partner_id": self._earlydryer_delivery_address().id,
                    "earlydryer_branch_id": branch.id,
                    "job_id": self.id,
                    "express": self.express,
                    "customer_note": self.customer_note or False,
                }
            )
            self.sudo().message_post(
                body=self.env._("Draft delivery %(stop)s created.", stop=stop.name),
                subtype_xmlid="mail.mt_note",
            )
            return stop
        group_ops = self.env.ref(GROUPS["operations_manager"])
        group_bm = self.env.ref(GROUPS["branch_manager"])
        users = branch.user_ids.filtered(
            lambda u: group_bm in u.all_group_ids and u.active
        ) or self.env["res.users"].search(
            [("group_ids", "in", group_ops.ids), ("share", "=", False)], limit=5
        )
        for user in users:
            self.sudo().activity_schedule(
                TODO_ACTIVITY,
                summary=self.env._("Arrange the delivery of %(job)s", job=self.name),
                user_id=user.id,
            )
        return Stop

    def action_earlydryer_arrange_delivery(self):
        """Arrange delivery wizard (any ready job, or one to deliver)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Arrange Delivery"),
            "res_model": "earlydryer.logistics.schedule.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_stop_type": "delivery",
                "default_job_id": self.id,
            },
        }

    def action_view_earlydryer_stops(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Pickups and Deliveries"),
            "res_model": "earlydryer.logistics.stop",
            "view_mode": "list,form",
            "domain": [("id", "in", self.earlydryer_stop_ids.ids)],
        }
