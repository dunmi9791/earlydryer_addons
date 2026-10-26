# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models
from odoo.exceptions import UserError

from ..models.earlydryer_approval_rule import APPROVAL_TYPES


class EarlydryerApprovalRequestWizard(models.TransientModel):
    _name = "earlydryer.approval.request.wizard"
    _description = "Request an Earlydryer Approval"

    res_model = fields.Char(required=True, readonly=True)
    res_id = fields.Many2oneReference(
        model_field="res_model", required=True, readonly=True
    )
    approval_type = fields.Selection(APPROVAL_TYPES, required=True, readonly=True)
    value = fields.Float(readonly=True)
    reason = fields.Text(required=True)

    def action_request(self):
        self.ensure_one()
        if self.res_model not in self.env:
            raise UserError(
                self.env._("Unknown document model %(model)s.", model=self.res_model)
            )
        document = self.env[self.res_model].browse(self.res_id).exists()
        if not document:
            raise UserError(self.env._("The document no longer exists."))
        if hasattr(document, "action_earlydryer_request_approval"):
            document.action_earlydryer_request_approval(
                self.approval_type, self.value, self.reason
            )
        else:
            document.check_access("read")
            self.env["earlydryer.approval.request"]._earlydryer_request_approval(
                self.res_model, self.res_id, self.approval_type, self.value, self.reason
            )
        return {"type": "ir.actions.act_window_close"}
