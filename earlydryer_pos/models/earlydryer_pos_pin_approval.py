# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerPosPinApproval(models.Model):
    """Log of every manager PIN given at a till (discount or credit)."""

    _name = "earlydryer.pos.pin.approval"
    _description = "Earlydryer Till PIN Approval"
    _order = "date desc, id desc"
    _rec_name = "employee_id"

    approval_type = fields.Selection(
        [("discount", "Discount"), ("credit", "Credit Release")],
        required=True,
        readonly=True,
    )
    employee_id = fields.Many2one(
        "hr.employee", string="Approved By", readonly=True, index=True
    )
    user_id = fields.Many2one(
        "res.users",
        string="Approver User",
        readonly=True,
        help="User of the approving employee (recorded on the approval request).",
    )
    cashier_employee_id = fields.Many2one(
        "hr.employee", string="Cashier", readonly=True
    )
    pos_config_id = fields.Many2one(
        "pos.config", string="Till", required=True, readonly=True, index=True
    )
    earlydryer_branch_id = fields.Many2one(
        related="pos_config_id.earlydryer_branch_id", store=True, index=True
    )
    pos_order_id = fields.Many2one("pos.order", readonly=True, ondelete="cascade")
    job_id = fields.Many2one("laundry.job", readonly=True, ondelete="cascade")
    rule_id = fields.Many2one("earlydryer.approval.rule", readonly=True)
    request_id = fields.Many2one("earlydryer.approval.request", readonly=True)
    value = fields.Float(readonly=True, help="Discount % or credit amount.")
    date = fields.Datetime(
        required=True,
        readonly=True,
        help="When the PIN was entered at the till (local time of the till, "
        "kept as is for offline approvals).",
    )
