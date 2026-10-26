# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class LaundryJobStageLog(models.Model):
    _inherit = "laundry.job.stage.log"
    earlydryer_release_unpaid = fields.Boolean(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(v) for v in vals_list]
        for vals in vals_list:
            if vals.get("to_state") in (
                "out_for_delivery",
                "collected",
                "delivered",
            ) and vals.get("job_id"):
                job = self.env["laundry.job"].browse(vals["job_id"])
                vals["earlydryer_release_unpaid"] = job.amount_due > 0
        return super().create(vals_list)
