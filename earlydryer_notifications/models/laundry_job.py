# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class LaundryJob(models.Model):
    _inherit = "laundry.job"
    earlydryer_notify_revision = fields.Integer(default=0, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        for job in jobs:
            if job.state == "received":
                self.env["earlydryer.notify.message"].notify(
                    "job_received", job, context={"occurrence": "created"}
                )
        return jobs

    def _earlydryer_on_state_changed(self, old_state, new_state):
        result = super()._earlydryer_on_state_changed(old_state, new_state)
        self.earlydryer_notify_revision += 1
        if old_state != new_state and new_state in (
            "received",
            "ready",
            "out_for_delivery",
            "delivered",
            "collected",
            "uncollected",
        ):
            self.env["earlydryer.notify.message"].notify(
                "job_" + new_state,
                self,
                context={"occurrence": str(self.earlydryer_notify_revision)},
            )
        return result

    def _earlydryer_send_uncollected_reminder(self, day):
        result = super()._earlydryer_send_uncollected_reminder(day)
        self.env["earlydryer.notify.message"].notify(
            "uncollected_reminder",
            self,
            context={"days_left": max(0, 14 - day), "occurrence": f"day:{day}"},
        )
        return result

    def _earlydryer_on_scan_mismatch(self, log):
        result = super()._earlydryer_on_scan_mismatch(log)
        self.env["earlydryer.notify.message"].notify(
            "alert_scan_mismatch", log, context={"occurrence": str(log.id)}
        )
        return result

    def _earlydryer_on_damage_found(self, rework):
        # Optional production hook; no dependency or registration of its models.
        parent = getattr(super(), "_earlydryer_on_damage_found", None)
        result = parent(rework) if parent else None
        self.env["earlydryer.notify.message"].notify(
            "alert_damage_found", self, context={"occurrence": f"damage:{rework.id}"}
        )
        return result

    def write(self, vals):
        newly = (
            self.filtered(lambda j: not j.earlydryer_released_unpaid)
            if vals.get("earlydryer_released_unpaid")
            else self.browse()
        )
        result = super().write(vals)
        for job in newly:
            self.env["earlydryer.notify.message"].notify(
                "alert_unpaid_release",
                job,
                context={"value": job.amount_due, "occurrence": "unpaid_release"},
            )
        return result
