# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from markupsafe import Markup
from odoo import models


class NotifyAlertRule(models.Model):
    _inherit = "earlydryer.notify.alert.rule"

    def _queue_email(self, partner, summary, branch, attachment=None):
        self.ensure_one()
        if self.event_id.code != "eod_report":
            return super()._queue_email(partner, summary, branch, attachment)
        # Existing one EOD email, with a canonical KPI section appended (no second pack email).
        day = self.env.context.get("earlydryer_report_date")
        if not day:
            from odoo import fields

            day = fields.Date.context_today(self.with_context(tz="Africa/Lagos"))
        user = partner.user_ids.filtered(lambda u: not u.share)[:1]
        if user:
            from ..tools import DASHBOARD_GROUPS, has_any

            service = (
                self.env["earlydryer.kpi"]
                .with_user(user)
                .with_company(branch.company_id)
            )
            kpis = (
                service.compute([], branch.ids, day, day)
                if has_any(service.env, DASHBOARD_GROUPS)
                else {}
            )
        else:
            kpis = (
                self.env["earlydryer.kpi"]
                .with_company(branch.company_id)
                .compute([], branch.ids, day, day)
            )
        rows = Markup("").join(
            Markup("<tr><td>{}</td><td>{:.2f}</td></tr>").format(v["label"], v["value"])
            for key, v in kpis.items()
            if not key.startswith("_")
        )
        body = Markup("<p>{}</p><h3>{}</h3><table>{}</table>").format(
            summary, self.env._("Performance indicators"), rows
        )
        mail = self.env["mail.mail"].create(
            {
                "subject": self.event_id.name + " - " + branch.name,
                "body_html": str(body),
                "email_to": partner.email,
                "email_from": branch.email
                or branch.company_id.email
                or "earlydryer@localhost",
                "attachment_ids": [(4, attachment.id)] if attachment else [],
            }
        )
        self.with_delay(
            channel="root.earlydryer_notify", identity_key=f"notify-mail:{mail.id}"
        )._send_mail(mail.id)
