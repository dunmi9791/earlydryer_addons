# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerApprovalMixin(models.AbstractModel):
    """Approval checks for documents (discounts, credit release, claims...).

    Typical use from an action button of an inheriting model::

        def action_confirm(self):
            for order in self:
                order._earlydryer_approval_ensure("discount", order.discount_percent)
            return super().action_confirm()

    The branch of the document (``earlydryer_branch_id`` when present) selects
    the branch-specific rules. Override ``_earlydryer_on_approval_decided`` to
    react to a decision.
    """

    _name = "earlydryer.approval.mixin"
    _description = "Earlydryer Approval Mixin"

    earlydryer_approval_request_ids = fields.Many2many(
        "earlydryer.approval.request",
        string="Approval Requests",
        compute="_compute_earlydryer_approval_request_ids",
    )
    earlydryer_approval_count = fields.Integer(
        string="Approvals",
        compute="_compute_earlydryer_approval_request_ids",
    )

    def _compute_earlydryer_approval_request_ids(self):
        requests = self.env["earlydryer.approval.request"].search(
            [("res_model", "=", self._name), ("res_id", "in", self.ids)]
        )
        requests_by_id = {}
        for request in requests:
            requests_by_id.setdefault(request.res_id, []).append(request.id)
        for record in self:
            record_requests = requests.browse(requests_by_id.get(record.id, []))
            record.earlydryer_approval_request_ids = record_requests
            record.earlydryer_approval_count = len(record_requests)

    def _earlydryer_approval_branch(self):
        self.ensure_one()
        if "earlydryer_branch_id" in self._fields:
            return self.earlydryer_branch_id
        return self.env["earlydryer.branch"]

    def _earlydryer_approval_rule(self, approval_type, value):
        self.ensure_one()
        return self.env["earlydryer.approval.request"]._earlydryer_approval_rule(
            self._name, approval_type, value, self._earlydryer_approval_branch()
        )

    def _earlydryer_approval_check(self, approval_type, value):
        self.ensure_one()
        return self.env["earlydryer.approval.request"]._earlydryer_approval_check(
            self._name,
            self.id,
            approval_type,
            value,
            self._earlydryer_approval_branch(),
        )

    def _earlydryer_approval_ensure(self, approval_type, value):
        self.ensure_one()
        return self.env["earlydryer.approval.request"]._earlydryer_approval_ensure(
            self._name,
            self.id,
            approval_type,
            value,
            self._earlydryer_approval_branch(),
        )

    def action_earlydryer_request_approval(self, approval_type, value, reason):
        self.ensure_one()
        self.check_access("read")
        return self.env["earlydryer.approval.request"]._earlydryer_request_approval(
            self._name,
            self.id,
            approval_type,
            value,
            reason,
            self._earlydryer_approval_branch(),
        )

    def _earlydryer_approval_wizard_action(self, approval_type, value):
        """Window action opening the "Request approval" wizard for this record."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Request Approval"),
            "res_model": "earlydryer.approval.request.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_approval_type": approval_type,
                "default_value": value,
            },
        }

    def action_view_earlydryer_approvals(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_base.earlydryer_approval_request_action_all"
        )
        action["domain"] = [("res_model", "=", self._name), ("res_id", "=", self.id)]
        action["context"] = {}
        return action

    def _earlydryer_on_approval_decided(self, request):
        """Hook called after ``request`` on this document was approved/rejected."""
        return
