# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import json

from odoo import api, fields, models


class NotifyEodReport(models.Model):
    _name = "earlydryer.notify.eod.report"
    _description = "Notification End of Day Delivery"
    branch_id = fields.Many2one("earlydryer.branch", required=True, ondelete="cascade")
    date = fields.Date(required=True)
    run_key = fields.Char(required=True, default="scheduled")
    state = fields.Selection([("queued", "Queued"), ("done", "Done")], default="queued")
    figures_json = fields.Text(readonly=True)
    attachment_id = fields.Many2one("ir.attachment", readonly=True)
    _day_unique = models.Constraint(
        "unique(branch_id,date,run_key)", "This daily report is already scheduled."
    )

    @api.model
    def _schedule(self, branch, day, run_key="scheduled"):
        self.env["earlydryer.notify.message"]._lock(f"eod:{branch.id}:{day}:{run_key}")
        old = self.search(
            [
                ("branch_id", "=", branch.id),
                ("date", "=", day),
                ("run_key", "=", run_key),
            ],
            limit=1,
        )
        if old:
            return old
        report = self.create({"branch_id": branch.id, "date": day, "run_key": run_key})
        report.with_delay(
            channel="root.earlydryer_notify", identity_key=f"eod:{report.id}"
        )._deliver()
        return report

    def _deliver(self):
        self.ensure_one()
        self = self.sudo()
        self.env.cr.execute(
            "SELECT id FROM earlydryer_notify_eod_report WHERE id=%s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()
        if self.state == "done":
            return
        branch = self.branch_id
        figures = branch._earlydryer_eod_figures(self.date)
        summary = "; ".join(f"{key}: {value}" for key, value in figures.items())
        attachment = self.env["ir.attachment"]
        if branch.eod_email_recipient_ids:
            pdf, _ = self.env["ir.actions.report"]._render_qweb_pdf(
                "earlydryer_accounting_ng.action_report_daily_cash",
                res_ids=branch.ids,
                data={"date": str(self.date)},
            )
            attachment = attachment.create(
                {
                    "name": f"daily-cash-{branch.code}-{self.date}.pdf",
                    "type": "binary",
                    "datas": base64.b64encode(pdf),
                    "mimetype": "application/pdf",
                    "res_model": self._name,
                    "res_id": self.id,
                }
            )
            rule = self.env.ref("earlydryer_notifications.rule_eod")
            for partner in branch.eod_email_recipient_ids.filtered("email"):
                rule._queue_email(partner, summary, branch, attachment)
        for partner in branch.eod_whatsapp_recipient_ids:
            self.env["earlydryer.notify.message"]._notify(
                "eod_report",
                branch,
                partner=partner,
                context={
                    "staff_recipient": True,
                    "summary": f"Orders {figures['orders']}; sales {figures['sales_value']:.2f}; cash {figures['cash']:.2f}; overdue {figures['overdue']}",
                    "orders": figures["orders"],
                    "sales_value": figures["sales_value"],
                    "cash": figures["cash"],
                    "overdue": figures["overdue"],
                    "occurrence": f"{self.date}:{self.run_key}",
                    "allowed_channels": ["whatsapp"],
                },
            )
        self.write(
            {
                "state": "done",
                "figures_json": json.dumps(figures),
                "attachment_id": attachment.id,
            }
        )
        if self.run_key == "scheduled":
            branch.eod_last_sent_on = self.date
