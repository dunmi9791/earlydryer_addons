# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.earlydryer_laundry_order.models.laundry_job import (
    STATES,
    TODO_ACTIVITY,
)

_logger = logging.getLogger(__name__)

# states a till may release from (cached for offline collection)
COLLECTABLE_STATES = ("ready", "packed", "out_for_delivery", "uncollected")
COLLECTION_CACHE_LIMIT = 2000
# context key: the release check already ran for the collection being recorded
RELEASE_CHECKED_CTX = "earlydryer_pos_release_checked"


class LaundryJob(models.Model):
    _inherit = "laundry.job"

    earlydryer_released_unpaid = fields.Boolean(
        string="Released Unpaid",
        readonly=True,
        copy=False,
        tracking=True,
        help="Collected at a till although the server found a balance due and "
        "no credit approval (offline collection from a stale cache).",
    )
    earlydryer_pos_collection_ids = fields.One2many(
        "earlydryer.pos.collection", "job_id", string="Till Collections"
    )

    # ------------------------------------------------------------------
    # Amounts of POS jobs
    # ------------------------------------------------------------------

    def _earlydryer_pos_amounts(self):
        """Amounts of a POS job from the accounting of its order.

        Total: the order without its balance-settlement lines. Due: the part
        paid with Customer Account methods that is still open on the
        customer's receivable (invoice, or the per-customer pay-later lines of
        the session entry, allocated oldest order first), less the settlement
        payments taken at a till and not yet reconciled by a session closing.
        Finance reconciling payments outside the POS lowers the due amount.
        """
        self.ensure_one()
        order = self.pos_order_id.sudo()
        if order.state not in ("paid", "done"):
            return super()._earlydryer_pos_amounts()
        total = order.amount_total - order._earlydryer_settlement_amount()
        due = order._earlydryer_pay_later_due() - self._earlydryer_pending_settlements()
        currency = order.currency_id
        due = currency.round(min(max(due, 0.0), total))
        return {"total": total, "paid": total - due}

    def _earlydryer_pending_settlements(self):
        """Settlement lines paying this job whose session is not closed yet
        (once closed, they are reconciled with the receivable)."""
        self.ensure_one()
        lines = (
            self.env["pos.order.line"]
            .sudo()
            .search(
                [
                    ("earlydryer_settlement_job_id", "=", self.id),
                    ("order_id.state", "in", ("paid", "done")),
                    ("order_id.session_id.state", "!=", "closed"),
                ]
            )
        )
        return sum(lines.mapped("price_subtotal_incl"))

    # ------------------------------------------------------------------
    # Release at the till
    # ------------------------------------------------------------------

    def _earlydryer_check_release(self):
        if self.env.context.get(RELEASE_CHECKED_CTX):
            return True
        return super()._earlydryer_check_release()

    def _earlydryer_pos_release_ok(self, user):
        """Run the release rule as ``user`` without raising.

        :returns: ``(ok, message)``
        """
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.with_user(user)._earlydryer_check_release()
        except UserError as error:
            return False, str(error)
        return True, ""

    def _earlydryer_flag_released_unpaid(self, message, collection=None):
        """The till released the job though the server finds it unpaid."""
        self.ensure_one()
        self.sudo().earlydryer_released_unpaid = True
        body = self.env._(
            "Released at the till although unpaid: %(message)s",
            message=message,
        )
        self.sudo().message_post(body=body, subtype_xmlid="mail.mt_note")
        for user in self._earlydryer_request_users():
            self.sudo().activity_schedule(
                TODO_ACTIVITY,
                summary=self.env._("%(job)s left the plant unpaid", job=self.name),
                note=message,
                user_id=user.id,
            )
        return True

    # ------------------------------------------------------------------
    # Tags written at the till
    # ------------------------------------------------------------------

    def _earlydryer_pos_apply_tags(self, garment_lines, employee=None):
        """Put the codes the till printed (or scanned) on the items.

        A code the server refuses (pre-printed tag already on an open job,
        code outside every range...) never fails the job: the item stays
        untagged with a conflict note, and the branch manager is told.
        Jobs whose items are all tagged move to Tagged.
        """
        self.ensure_one()
        conflicts = []
        for line in garment_lines:
            codes = line._earlydryer_tag_code_list()
            items = self.item_ids.filtered(
                lambda item, line=line: item.pos_line_id == line
            ).sorted(lambda item: (item.sequence, item.id))
            for item, code in zip(items, codes, strict=False):
                if not item.tag_required:
                    continue
                # duplicates within the order are refused by the uniqueness
                # constraint like codes held by other jobs
                try:
                    with self.env.cr.savepoint():
                        item.sudo().tag_code = code
                except (ValidationError, UserError) as error:
                    conflicts.append((item, code, str(error)))
        for item, code, message in conflicts:
            item.sudo().earlydryer_tag_conflict = self.env._(
                "%(code)s refused: %(message)s", code=code, message=message
            )
        if conflicts:
            details = "; ".join(
                f"{item.display_name}: {code} ({message})"
                for item, code, message in conflicts
            )
            self.sudo().message_post(
                body=self.env._(
                    "Tags refused at sync, tag these items again: %(details)s",
                    details=details,
                ),
                subtype_xmlid="mail.mt_note",
            )
            for user in self._earlydryer_request_users():
                self.sudo().activity_schedule(
                    TODO_ACTIVITY,
                    summary=self.env._("Retag items of %(job)s", job=self.name),
                    note=details,
                    user_id=user.id,
                )
        if self.state == "received" and self.item_ids and self._check_can_tag():
            self.sudo().action_move_to("tagged", employee=employee or None)
        return conflicts

    # ------------------------------------------------------------------
    # Collection at the till
    # ------------------------------------------------------------------

    def _earlydryer_pos_card(self):
        """Plain values the till shows and caches for collection."""
        self.ensure_one()
        job = self.sudo()
        due = job.amount_due
        order = job.pos_order_id
        return {
            "id": job.id,
            "name": job.name,
            "state": job.state,
            "state_label": dict(STATES).get(job.state, job.state),
            "partner_id": job.partner_id.id,
            "partner_name": job.partner_id.name or "",
            "partner_phone": job.partner_id.phone or "",
            "pos_reference": order.pos_reference or "",
            "tags": [code for code in job.item_ids.mapped("tag_code") if code],
            "item_count": job.item_count,
            "shelf": job.shelf_id.name or "",
            "amount_due": due,
            "credit_approved": bool(due) and job._earlydryer_credit_approved(due),
            "promised_on": fields.Datetime.to_string(job.promised_on)
            if job.promised_on
            else False,
            "express": job.express,
            "fulfilment": job.fulfilment,
        }

    @api.model
    def _earlydryer_pos_collection_cache(
        self, branch, days, limit=COLLECTION_CACHE_LIMIT
    ):
        """Ready, packed, out-for-delivery and uncollected jobs of ``branch``
        changed in the last ``days`` days, newest first, at most ``limit``."""
        since = fields.Datetime.subtract(fields.Datetime.now(), days=max(days, 1))
        jobs = self.sudo().search(
            [
                ("earlydryer_branch_id", "=", branch.id),
                ("state", "in", COLLECTABLE_STATES),
                ("write_date", ">=", since),
            ],
            order="write_date desc, id desc",
            limit=limit + 1,
        )
        return {
            "jobs": [job._earlydryer_pos_card() for job in jobs[:limit]],
            "capped": len(jobs) > limit,
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
        }

    @api.model
    def earlydryer_pos_collection_info(self, job_id, config_id):
        """RPC of the collection screen: the job card, read fresh."""
        config = self.env["pos.config"].browse(config_id)
        config._earlydryer_check_till_access()
        job = self.browse(job_id).exists()
        if not job or job.sudo().earlydryer_branch_id != config.earlydryer_branch_id:
            return False
        job.check_access("read")
        return job._earlydryer_pos_card()

    @api.model
    def earlydryer_pos_lookup(self, code, config_id):
        """Find a job by receipt barcode (order reference), tag or job number,
        or a list of jobs by phone or customer name."""
        config = self.env["pos.config"].browse(config_id)
        config._earlydryer_check_till_access()
        branch = config.earlydryer_branch_id
        code = (code or "").strip()
        if not code:
            return {"jobs": []}
        order = self.env["pos.order"].search([("pos_reference", "=", code)], limit=1)
        if order and order.earlydryer_job_id:
            jobs = order.earlydryer_job_id
        else:
            scan = self.earlydryer_scan_lookup(code, branch_id=branch.id, log=True)
            if scan.get("job_id"):
                jobs = self.browse(scan["job_id"])
            else:
                jobs = self.search(
                    [
                        ("earlydryer_branch_id", "=", branch.id),
                        "|",
                        "|",
                        ("partner_phone", "ilike", code),
                        ("partner_id.name", "ilike", code),
                        ("name", "ilike", code),
                    ],
                    order="received_on desc",
                    limit=20,
                )
        jobs = jobs.filtered(lambda job: job.earlydryer_branch_id == branch)
        return {"jobs": [job._earlydryer_pos_card() for job in jobs]}
