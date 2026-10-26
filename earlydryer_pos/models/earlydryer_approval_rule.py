# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models
from odoo.fields import Domain

# approvals the till asks for: discounts at intake, credit at collection
POS_APPROVALS = [("pos.order", "discount"), ("laundry.job", "credit")]


class EarlydryerApprovalRule(models.Model):
    _name = "earlydryer.approval.rule"
    _inherit = ["earlydryer.approval.rule", "pos.load.mixin"]

    @api.model
    def _earlydryer_pos_rule_domain(self, branch):
        """Active discount and credit rules a till of ``branch`` applies."""
        kinds = Domain.OR(
            Domain([("model_name", "=", model), ("approval_type", "=", kind)])
            for model, kind in POS_APPROVALS
        )
        branch_domain = Domain("branch_ids", "=", False)
        if branch:
            branch_domain |= Domain("branch_ids", "in", branch.ids)
        return kinds & branch_domain

    @api.model
    def _load_pos_data_domain(self, data, config):
        if not config.earlydryer_enabled:
            return False
        return self._earlydryer_pos_rule_domain(config.earlydryer_branch_id)

    @api.model
    def _load_pos_data_search_read(self, data, config):
        # Front Desk users cannot always read every rule's group: plain values
        # of active rules only, read with sudo
        domain = self._load_pos_data_domain(data, config)
        if domain is False:
            return []
        rules = self.sudo().search(domain, order="sequence, id")
        return rules.read(self._load_pos_data_fields(config), load=False)

    @api.model
    def _load_pos_data_fields(self, config):
        # the approver group is resolved per employee on the server
        # (hr.employee _earlydryer_rule_ids): never needed in the browser
        return [
            "id",
            "name",
            "sequence",
            "approval_type",
            "model_name",
            "threshold_kind",
            "min_value",
            "max_value",
            "self_approve",
        ]

    def _server_date_to_domain(self, domain):
        return domain
