# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain

APPROVAL_TYPES = [
    ("discount", "Discount"),
    ("credit", "Credit Release"),
    ("claim", "Claim Outcome"),
    ("purchase", "Purchase"),
    ("other", "Other"),
]


class EarlydryerApprovalRule(models.Model):
    """When a document action needs approval, and by whom.

    Only plain stored fields are used for matching (see ``_earlydryer_match``)
    so the offline POS can load the rules and apply the same logic client side.
    """

    _name = "earlydryer.approval.rule"
    _description = "Earlydryer Approval Rule"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    approval_type = fields.Selection(
        APPROVAL_TYPES, required=True, default="discount", index=True
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Document Model",
        required=True,
        index=True,
        ondelete="cascade",
    )
    model_name = fields.Char(
        related="model_id.model",
        store=True,
        index=True,
    )
    branch_ids = fields.Many2many(
        "earlydryer.branch",
        string="Branches",
        help="Leave empty to apply the rule on all branches.",
    )
    threshold_kind = fields.Selection(
        [("amount", "Amount"), ("percent", "Percent")],
        required=True,
        default="percent",
    )
    min_value = fields.Float(
        string="Above",
        help="The rule applies when the value is strictly greater than this.",
    )
    max_value = fields.Float(
        string="Up To",
        help="The rule applies up to and including this value. 0 means no limit.",
    )
    approver_group_id = fields.Many2one(
        "res.groups",
        required=True,
        ondelete="restrict",
        help="Users of this group approve the requests matched by this rule.",
    )
    self_approve = fields.Boolean(
        help="When the requesting user belongs to the approver group, the "
        "request is approved at once and logged.",
    )
    note = fields.Text()

    @api.constrains("min_value", "max_value", "threshold_kind")
    def _check_values(self):
        for rule in self:
            if rule.min_value < 0 or rule.max_value < 0:
                raise ValidationError(
                    self.env._(
                        "Rule %(rule)s: values cannot be negative.", rule=rule.name
                    )
                )
            if rule.max_value and rule.min_value >= rule.max_value:
                raise ValidationError(
                    self.env._(
                        "Rule %(rule)s: 'Above' must be lower than 'Up To'.",
                        rule=rule.name,
                    )
                )
            if rule.threshold_kind == "percent" and (
                rule.min_value > 100 or rule.max_value > 100
            ):
                raise ValidationError(
                    self.env._(
                        "Rule %(rule)s: percentages must be between 0 and 100.",
                        rule=rule.name,
                    )
                )

    @api.model
    def _earlydryer_match_domain(self, model_name, approval_type, value, branch=None):
        domain = Domain(
            [
                ("model_name", "=", model_name),
                ("approval_type", "=", approval_type),
                ("min_value", "<", value),
            ]
        ) & (Domain("max_value", "=", 0) | Domain("max_value", ">=", value))
        if branch:
            domain &= Domain("branch_ids", "=", False) | Domain(
                "branch_ids", "in", branch.ids
            )
        else:
            domain &= Domain("branch_ids", "=", False)
        return domain

    @api.model
    def _earlydryer_match(self, model_name, approval_type, value, branch=None):
        """Active rule with the lowest sequence whose range contains ``value``.

        Rules restricted to branches only apply to documents of those branches.
        Returns an empty recordset when no approval is needed.
        """
        domain = self._earlydryer_match_domain(model_name, approval_type, value, branch)
        rule = self.sudo().search(domain, order="sequence, id", limit=1)
        return self.browse(rule.id)
