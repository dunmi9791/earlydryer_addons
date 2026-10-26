# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class LaundryJobItem(models.Model):
    _inherit = "laundry.job.item"
    earlydryer_missing_on = fields.Datetime(readonly=True, index=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for item in records:
            if item.missing:
                stamp = item.earlydryer_missing_on or fields.Datetime.now()
                item.sudo().write({"earlydryer_missing_on": stamp})
                self.env["earlydryer.report.qc.event"].sudo().create(
                    {"item_id": item.id, "result": "missing", "date": stamp}
                )
        return records

    def write(self, vals):
        old = {item.id: (item.qc_state, item.missing) for item in self}
        result = super().write(vals)
        for item in self:
            if "missing" in vals and bool(vals["missing"]) != old[item.id][1]:
                stamp = vals.get("earlydryer_missing_on") or fields.Datetime.now()
                if vals["missing"]:
                    super(LaundryJobItem, item.sudo()).write(
                        {"earlydryer_missing_on": stamp}
                    )
                self.env["earlydryer.report.qc.event"].sudo().create(
                    {
                        "item_id": item.id,
                        "result": "missing" if vals["missing"] else "found",
                        "date": stamp,
                    }
                )
            if (
                vals.get("qc_state") in ("rework", "passed")
                and old[item.id][0] != item.qc_state
            ):
                self.env["earlydryer.report.qc.event"].sudo().create(
                    {
                        "item_id": item.id,
                        "result": "failed" if item.qc_state == "rework" else "passed",
                        "date": item.qc_date or fields.Datetime.now(),
                    }
                )
        return result
