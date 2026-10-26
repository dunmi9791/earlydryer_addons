# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

# context key allowing the engine itself to set the protected fields
INTERNAL_CTX = "earlydryer_approval_internal"
PROTECTED_FIELDS = {
    "rule_id",
    "res_model",
    "res_id",
    "value",
    "state",
    "requested_by_id",
    "requested_on",
    "decided_by_id",
    "decided_on",
    "approver_user_ids",
    "earlydryer_branch_id",
    "company_id",
}
TODO_ACTIVITY = "mail.mail_activity_data_todo"


class EarlydryerApprovalRequest(models.Model):
    _name = "earlydryer.approval.request"
    _description = "Earlydryer Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "requested_on desc, id desc"

    name = fields.Char(
        required=True, readonly=True, copy=False, default=lambda self: self.env._("New")
    )
    rule_id = fields.Many2one(
        "earlydryer.approval.rule",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    approval_type = fields.Selection(
        related="rule_id.approval_type", store=True, index=True
    )
    approver_group_id = fields.Many2one(
        related="rule_id.approver_group_id", store=True, index=True
    )
    threshold_kind = fields.Selection(related="rule_id.threshold_kind")
    res_model = fields.Char(
        string="Document Model", required=True, readonly=True, index=True
    )
    res_id = fields.Many2oneReference(
        string="Document ID",
        model_field="res_model",
        required=True,
        readonly=True,
        index=True,
    )
    res_name = fields.Char(string="Document", compute="_compute_res_name")
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch", string="Branch", readonly=True, index=True
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    value = fields.Float(readonly=True)
    reason = fields.Text(required=True)
    decision_note = fields.Text()
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending",
        readonly=True,
        tracking=True,
        index=True,
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, readonly=True, default=lambda self: self.env.user
    )
    requested_on = fields.Datetime(
        required=True, readonly=True, default=fields.Datetime.now
    )
    decided_by_id = fields.Many2one("res.users", readonly=True)
    decided_on = fields.Datetime(readonly=True)
    approver_user_ids = fields.Many2many(
        "res.users",
        "earlydryer_approval_request_approver_rel",
        "request_id",
        "user_id",
        string="Notified Approvers",
        readonly=True,
    )
    can_decide = fields.Boolean(
        compute="_compute_can_decide", search="_search_can_decide"
    )

    @api.depends("res_model", "res_id")
    def _compute_res_name(self):
        for request in self:
            document = request.sudo()._earlydryer_document()
            request.res_name = document.display_name if document else False

    @api.depends_context("uid")
    @api.depends("approver_group_id")
    def _compute_can_decide(self):
        user_groups = self.env.user.all_group_ids
        for request in self:
            request.can_decide = request.approver_group_id in user_groups

    def _search_can_decide(self, operator, value):
        if operator not in ("in", "not in"):
            return NotImplemented
        domain = Domain("approver_group_id", "in", self.env.user.all_group_ids.ids)
        return domain if (True in value) == (operator == "in") else ~domain

    @api.constrains("state", "res_model", "res_id", "approval_type")
    def _check_single_pending(self):
        for request in self.filtered(lambda r: r.state == "pending"):
            duplicate = self.sudo().search_count(
                [
                    ("id", "!=", request.id),
                    ("state", "=", "pending"),
                    ("res_model", "=", request.res_model),
                    ("res_id", "=", request.res_id),
                    ("approval_type", "=", request.approval_type),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    self.env._(
                        "A %(type)s approval is already pending for %(document)s.",
                        type=request._earlydryer_type_label(),
                        document=request.res_name or request.res_model,
                    )
                )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        internal = self.env.context.get(INTERNAL_CTX)
        for vals in vals_list:
            if not internal:
                # only the engine may create decided requests
                vals.update(
                    state="pending",
                    requested_by_id=self.env.uid,
                    requested_on=fields.Datetime.now(),
                    decided_by_id=False,
                    decided_on=False,
                    approver_user_ids=False,
                )
            if not vals.get("name") or vals["name"] == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code(
                    "earlydryer.approval.request"
                ) or self.env._("New")
        requests = super().create(vals_list)
        for request in requests:
            request._earlydryer_check_document()
            if request.state == "pending":
                request._earlydryer_notify_approvers()
                body = self.env._(
                    "Approval %(name)s requested (%(type)s, %(value)s): %(reason)s",
                    name=request.name,
                    type=request._earlydryer_type_label(),
                    value=request._earlydryer_value_label(),
                    reason=request.reason,
                )
            else:
                body = self.env._(
                    "Approval %(name)s (%(type)s, %(value)s) self-approved "
                    "by %(user)s.",
                    name=request.name,
                    type=request._earlydryer_type_label(),
                    value=request._earlydryer_value_label(),
                    user=request.decided_by_id.name,
                )
            request._earlydryer_post_on_document(body)
        # auditlog (full mode) re-reads every field of the new requests in
        # another context; flush the activities scheduled above first, or their
        # pending computed values cannot be flushed from that context
        self.env["mail.activity"].flush_model()
        return requests

    def write(self, vals):
        if (
            not self.env.su
            and not self.env.context.get(INTERNAL_CTX)
            and PROTECTED_FIELDS & vals.keys()
        ):
            raise UserError(
                self.env._(
                    "Approval requests can only be changed through their "
                    "Approve, Reject and Cancel buttons."
                )
            )
        return super().write(vals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _earlydryer_type_label(self):
        self.ensure_one()
        return dict(self._fields["approval_type"]._description_selection(self.env)).get(
            self.approval_type, self.approval_type
        )

    def _earlydryer_value_label(self):
        self.ensure_one()
        if self.rule_id.threshold_kind == "percent":
            return f"{self.value:g}%"
        return f"{self.value:,.2f}"

    def _earlydryer_document(self):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return False
        return self.env[self.res_model].browse(self.res_id).exists()

    def _earlydryer_check_document(self):
        self.ensure_one()
        if self.res_model not in self.env:
            raise ValidationError(
                self.env._("Unknown document model %(model)s.", model=self.res_model)
            )
        if self.rule_id.model_name != self.res_model:
            raise ValidationError(
                self.env._(
                    "Rule %(rule)s does not apply to %(model)s documents.",
                    rule=self.rule_id.name,
                    model=self.res_model,
                )
            )

    def _earlydryer_post_on_document(self, body):
        self.ensure_one()
        document = self._earlydryer_document()
        if document and "message_ids" in document._fields:  # inherits mail.thread
            document.sudo().message_post(body=body, subtype_xmlid="mail.mt_note")

    def _earlydryer_get_approver_users(self):
        """Approver group users allowed on the request's branch.

        Falls back to every user of the group when nobody is allowed there.
        """
        self.ensure_one()
        users = self.rule_id.sudo().approver_group_id.all_user_ids.filtered(
            lambda u: u.active and not u.share
        )
        branch = self.earlydryer_branch_id
        if branch:
            on_branch = users.filtered(
                lambda u: (
                    branch in u.earlydryer_branch_ids
                    or u._earlydryer_has_all_branches()
                )
            )
            users = on_branch or users
        return users

    def _earlydryer_notify_approvers(self):
        self.ensure_one()
        users = self._earlydryer_get_approver_users()
        self.sudo().with_context(**{INTERNAL_CTX: True}).approver_user_ids = users
        summary = self.env._("Approve %(name)s", name=self.name)
        for user in users:
            self.activity_schedule(
                TODO_ACTIVITY, summary=summary, note=self.reason, user_id=user.id
            )

    def _earlydryer_user_can_decide(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        return self.rule_id.sudo().approver_group_id in user.all_group_ids

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _earlydryer_decide(self, state):
        for request in self:
            if not request._earlydryer_user_can_decide():
                raise AccessError(
                    self.env._(
                        "Only members of %(group)s can approve or reject %(name)s.",
                        group=request.rule_id.sudo().approver_group_id.display_name,
                        name=request.name,
                    )
                )
            if request.state != "pending":
                raise UserError(
                    self.env._("%(name)s is no longer pending.", name=request.name)
                )
        self.sudo().with_context(**{INTERNAL_CTX: True}).write(
            {
                "state": state,
                "decided_by_id": self.env.uid,
                "decided_on": fields.Datetime.now(),
            }
        )
        for request in self:
            if state == "approved":
                body = self.env._(
                    "%(name)s approved by %(user)s.",
                    name=request.name,
                    user=self.env.user.name,
                )
            else:
                body = self.env._(
                    "%(name)s rejected by %(user)s.",
                    name=request.name,
                    user=self.env.user.name,
                )
            if request.decision_note:
                body = f"{body} {request.decision_note}"
            request.sudo().activity_feedback([TODO_ACTIVITY], feedback=body)
            request.message_post(body=body, subtype_xmlid="mail.mt_note")
            request._earlydryer_post_on_document(body)
            document = request._earlydryer_document()
            if document and hasattr(document, "_earlydryer_on_approval_decided"):
                document._earlydryer_on_approval_decided(request)
        return True

    def action_approve(self):
        return self._earlydryer_decide("approved")

    def action_reject(self):
        return self._earlydryer_decide("rejected")

    def action_cancel(self):
        for request in self:
            if request.state != "pending":
                raise UserError(
                    self.env._("%(name)s is no longer pending.", name=request.name)
                )
            if (
                request.requested_by_id != self.env.user
                and not request._earlydryer_user_can_decide()
            ):
                raise AccessError(
                    self.env._(
                        "Only the requester or an approver can cancel %(name)s.",
                        name=request.name,
                    )
                )
        self.sudo().with_context(**{INTERNAL_CTX: True}).write({"state": "cancelled"})
        for request in self:
            body = self.env._(
                "%(name)s cancelled by %(user)s.",
                name=request.name,
                user=self.env.user.name,
            )
            request.sudo().activity_unlink([TODO_ACTIVITY])
            request.message_post(body=body, subtype_xmlid="mail.mt_note")
            request._earlydryer_post_on_document(body)
        return True

    def action_open_document(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
        }

    # ------------------------------------------------------------------
    # Engine (used by earlydryer.approval.mixin)
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_document_branch(self, res_model, res_id):
        document = self.env[res_model].browse(res_id)
        if "earlydryer_branch_id" in document._fields:
            return document.sudo().earlydryer_branch_id
        return self.env["earlydryer.branch"]

    @api.model
    def _earlydryer_approval_rule(self, res_model, approval_type, value, branch=None):
        return self.env["earlydryer.approval.rule"]._earlydryer_match(
            res_model, approval_type, value, branch
        )

    @api.model
    def _earlydryer_approval_check(
        self, res_model, res_id, approval_type, value, branch=None
    ):
        """True when the document may proceed without (further) approval."""
        if branch is None:
            branch = self._earlydryer_document_branch(res_model, res_id)
        rule = self._earlydryer_approval_rule(res_model, approval_type, value, branch)
        if not rule:
            return True
        approved = self.sudo().search_count(
            [
                ("res_model", "=", res_model),
                ("res_id", "=", res_id),
                ("approval_type", "=", approval_type),
                ("state", "=", "approved"),
                ("value", ">=", value),
            ],
            limit=1,
        )
        if approved:
            return True
        if rule.sudo().self_approve and rule.sudo().approver_group_id in (
            self.env.user.all_group_ids
        ):
            now = fields.Datetime.now()
            self.with_context(**{INTERNAL_CTX: True}).create(
                {
                    "rule_id": rule.id,
                    "res_model": res_model,
                    "res_id": res_id,
                    "earlydryer_branch_id": branch.id if branch else False,
                    "value": value,
                    "reason": self.env._("Self-approved"),
                    "state": "approved",
                    "decided_by_id": self.env.uid,
                    "decided_on": now,
                }
            )
            return True
        return False

    @api.model
    def _earlydryer_approval_ensure(
        self, res_model, res_id, approval_type, value, branch=None
    ):
        if branch is None:
            branch = self._earlydryer_document_branch(res_model, res_id)
        if self._earlydryer_approval_check(
            res_model, res_id, approval_type, value, branch
        ):
            return True
        rule = self._earlydryer_approval_rule(res_model, approval_type, value, branch)
        type_label = dict(
            self.env["earlydryer.approval.rule"]
            ._fields["approval_type"]
            ._description_selection(self.env)
        ).get(approval_type, approval_type)
        raise UserError(
            self.env._(
                "This %(type)s needs approval by %(group)s (rule %(rule)s). "
                "Request an approval first.",
                type=type_label,
                group=rule.sudo().approver_group_id.display_name,
                rule=rule.name,
            )
        )

    @api.model
    def _earlydryer_request_approval(
        self, res_model, res_id, approval_type, value, reason, branch=None
    ):
        if branch is None:
            branch = self._earlydryer_document_branch(res_model, res_id)
        rule = self._earlydryer_approval_rule(res_model, approval_type, value, branch)
        if not rule:
            raise UserError(
                self.env._("No approval rule applies: no approval is needed.")
            )
        if not (reason or "").strip():
            raise UserError(
                self.env._("Please give a reason for the approval request.")
            )
        pending = self.sudo().search_count(
            [
                ("res_model", "=", res_model),
                ("res_id", "=", res_id),
                ("approval_type", "=", approval_type),
                ("state", "=", "pending"),
            ],
            limit=1,
        )
        if pending:
            raise UserError(
                self.env._(
                    "An approval request of this type is already pending for "
                    "this document."
                )
            )
        document = self.env[res_model].browse(res_id)
        company = (
            document.sudo().company_id
            if "company_id" in document._fields and document.sudo().company_id
            else (branch.company_id if branch else self.env.company)
        )
        return self.create(
            {
                "rule_id": rule.id,
                "res_model": res_model,
                "res_id": res_id,
                "earlydryer_branch_id": branch.id if branch else False,
                "company_id": company.id,
                "value": value,
                "reason": reason,
            }
        )
