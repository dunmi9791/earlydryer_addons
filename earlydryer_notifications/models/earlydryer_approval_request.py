# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class ApprovalRequest(models.Model):
    _inherit = "earlydryer.approval.request"

    def write(self, vals):
        approved = (
            self.filtered(lambda r: r.state != "approved")
            if vals.get("state") == "approved"
            else self.browse()
        )
        result = super().write(vals)
        for approval in approved:
            code = {
                "discount": "alert_large_discount",
                "credit": "alert_unpaid_release",
            }.get(approval.approval_type)
            if code:
                self.env["earlydryer.notify.message"].notify(
                    code,
                    approval,
                    context={"value": approval.value, "occurrence": str(approval.id)},
                )
        return result
