# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.earlydryer_base.models.earlydryer_approval_request import (
    INTERNAL_CTX,
)

from .laundry_job import COLLECTABLE_STATES, RELEASE_CHECKED_CTX

_logger = logging.getLogger(__name__)

MODES = [
    ("paid", "Paid"),
    ("credit", "Manager Credit"),
    ("settlement", "Paid at Collection"),
]


class EarlydryerPosCollection(models.Model):
    """A release recorded at a till, sent when the till is online.

    Idempotent per ``uuid``. What happened at the counter is never reversed:
    when the server finds the job unpaid the collection is still recorded and
    the job flagged *Released Unpaid* for the branch manager.
    """

    _name = "earlydryer.pos.collection"
    _description = "Earlydryer Till Collection"
    _order = "collected_on desc, id desc"
    _rec_name = "job_id"

    uuid = fields.Char(required=True, readonly=True, copy=False)
    pos_config_id = fields.Many2one(
        "pos.config", string="Till", required=True, readonly=True, index=True
    )
    session_id = fields.Many2one("pos.session", readonly=True)
    earlydryer_branch_id = fields.Many2one(
        related="pos_config_id.earlydryer_branch_id", store=True, index=True
    )
    job_id = fields.Many2one(
        "laundry.job", required=True, readonly=True, index=True, ondelete="cascade"
    )
    employee_id = fields.Many2one("hr.employee", string="Released By", readonly=True)
    mode = fields.Selection(MODES, required=True, readonly=True)
    approver_employee_id = fields.Many2one(
        "hr.employee", string="Credit Approved By", readonly=True
    )
    amount_due_seen = fields.Float(
        string="Due at the Till", readonly=True, help="Balance the till showed."
    )
    settlement_order_uuid = fields.Char(readonly=True)
    collected_on = fields.Datetime(required=True, readonly=True)
    state = fields.Selection(
        [
            ("done", "Collected"),
            ("released_unpaid", "Released Unpaid"),
            ("refused", "Not Recorded"),
        ],
        required=True,
        readonly=True,
        default="done",
    )
    message = fields.Text(readonly=True)

    _uuid_uniq = models.Constraint(
        "unique(uuid)", "This collection was already recorded."
    )

    @api.model
    def earlydryer_pos_submit(self, config_id, collections):
        """RPC of the till: record queued collections.

        :param collections: list of dicts ``{uuid, job_id, employee_id, mode,
            approver_employee_id, amount_due, collected_on,
            settlement_order_uuid}``
        :returns: list of ``{uuid, status, message}``; ``pending`` means
            "send again later" (settlement order not synced yet)
        """
        config = self.env["pos.config"].browse(config_id)
        config._earlydryer_check_till_access()
        results = []
        for vals in collections:
            existing = self.sudo().search([("uuid", "=", vals["uuid"])], limit=1)
            if existing:
                results.append(existing._earlydryer_result())
                continue
            settlement_uuid = vals.get("settlement_order_uuid")
            if settlement_uuid and not self.env["pos.order"].sudo().search_count(
                [("uuid", "=", settlement_uuid), ("state", "in", ("paid", "done"))],
                limit=1,
            ):
                results.append(
                    {"uuid": vals["uuid"], "status": "pending", "message": ""}
                )
                continue
            with self.env.cr.savepoint():
                collection = self.sudo()._earlydryer_record(config, vals)
            results.append(collection._earlydryer_result())
        return results

    def _earlydryer_result(self):
        self.ensure_one()
        return {"uuid": self.uuid, "status": self.state, "message": self.message or ""}

    @api.model
    def _earlydryer_record(self, config, vals):
        Job = self.env["laundry.job"].sudo()
        Employee = self.env["hr.employee"].sudo()
        job = Job.browse(vals["job_id"]).exists()
        if not job or job.earlydryer_branch_id != config.earlydryer_branch_id:
            raise AccessError(self.env._("This job belongs to another plant."))
        employee = Employee.browse(vals.get("employee_id") or []).exists()
        approver = Employee.browse(vals.get("approver_employee_id") or []).exists()
        collection = self.create(
            {
                "uuid": vals["uuid"],
                "pos_config_id": config.id,
                "session_id": config.current_session_id.id,
                "job_id": job.id,
                "employee_id": employee.id,
                "mode": vals.get("mode") or "paid",
                "approver_employee_id": approver.id,
                "amount_due_seen": vals.get("amount_due") or 0.0,
                "settlement_order_uuid": vals.get("settlement_order_uuid") or False,
                "collected_on": vals.get("collected_on") or fields.Datetime.now(),
            }
        )
        collection._earlydryer_process()
        return collection

    def _earlydryer_check_user(self):
        """Whose rights the release rule runs with: the approving manager for
        a credit, else the collecting employee's user, else the session's."""
        self.ensure_one()
        if self.mode == "credit" and self.approver_employee_id.user_id:
            return self.approver_employee_id.user_id
        return self.employee_id.user_id or self.session_id.user_id or self.env.user

    def _earlydryer_log_credit(self):
        """Approved credit request and PIN log of a manager's credit."""
        self.ensure_one()
        job = self.job_id
        due = job.amount_due
        approver = self.approver_employee_id
        user = approver.user_id
        request = self.env["earlydryer.approval.request"]
        rule = job._earlydryer_approval_rule("credit", due) if due > 0 else False
        if rule and user and rule.sudo().approver_group_id in user.all_group_ids:
            if not job._earlydryer_credit_approved(due):
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
                            "value": due,
                            "reason": self.env._(
                                "Credit approved at till %(pos)s by %(employee)s "
                                "(PIN).",
                                pos=self.pos_config_id.name,
                                employee=approver.name,
                            ),
                            "state": "approved",
                            "requested_by_id": (
                                self.employee_id.user_id or self.env.user
                            ).id,
                            "requested_on": self.collected_on,
                            "decided_by_id": user.id,
                            "decided_on": self.collected_on,
                        }
                    )
                )
        self.env["earlydryer.pos.pin.approval"].sudo().create(
            {
                "approval_type": "credit",
                "employee_id": approver.id,
                "user_id": user.id,
                "cashier_employee_id": self.employee_id.id,
                "pos_config_id": self.pos_config_id.id,
                "job_id": job.id,
                "rule_id": rule.id if rule else False,
                "request_id": request.id,
                "value": due,
                "date": self.collected_on,
            }
        )

    def _earlydryer_process(self):
        self.ensure_one()
        job = self.job_id
        if job.state in ("collected", "delivered"):
            self.write({"message": self.env._("Already %(state)s.", state=job.state)})
            return
        if job.state not in COLLECTABLE_STATES:
            self.write(
                {
                    "state": "refused",
                    "message": self.env._(
                        "Job is %(state)s: it cannot be collected.", state=job.state
                    ),
                }
            )
            job._earlydryer_flag_released_unpaid(self.message)
            return
        if self.mode == "credit" and self.approver_employee_id:
            self._earlydryer_log_credit()
        ok, message = job._earlydryer_pos_release_ok(self._earlydryer_check_user())
        if not ok:
            self.write({"state": "released_unpaid", "message": message})
            job._earlydryer_flag_released_unpaid(message, collection=self)
        mode_label = dict(MODES)[self.mode]
        note = self.env._(
            "Collected at till %(pos)s on %(date)s (%(mode)s).",
            pos=self.pos_config_id.name,
            date=fields.Datetime.to_string(self.collected_on),
            mode=mode_label,
        )
        if not ok:
            note = f"{note} {self.env._('Released unpaid')}: {message}"
        job.with_context(**{RELEASE_CHECKED_CTX: True}).action_move_to(
            "collected", employee=self.employee_id, note=note
        )
