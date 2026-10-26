# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64

from odoo import models

from ..tools import DASHBOARD_GROUPS, has_any, scope


class NotifyEodReport(models.Model):
    _inherit = "earlydryer.notify.eod.report"

    def _deliver(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM earlydryer_notify_eod_report WHERE id=%s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()
        if self.state == "done":
            return
        result = super(
            NotifyEodReport, self.with_context(earlydryer_report_date=self.date)
        )._deliver()
        subscriptions = (
            self.env["earlydryer.report.subscription"]
            .sudo()
            .search(
                [
                    ("active", "=", True),
                    ("frequency", "=", "daily"),
                    ("company_id", "=", self.branch_id.company_id.id),
                ]
            )
        )
        branch = self.branch_id
        rule = (
            self.env.ref("earlydryer_notifications.rule_eod")
            .sudo()
            .with_context(earlydryer_report_date=self.date)
        )
        for sub in subscriptions:
            owner = sub.user_id or sub.owner_user_id
            if not has_any(sub.with_user(owner).env, DASHBOARD_GROUPS):
                continue
            recipient_env = (
                sub.with_user(owner)
                .with_context(allowed_company_ids=[sub.company_id.id])
                .env
            )
            allowed = scope(recipient_env, sub.branch_ids.ids)
            if branch not in allowed:
                continue
            partner = sub.user_id.partner_id or sub.partner_id
            if (
                sub.email
                and partner.email
                and partner not in branch.eod_email_recipient_ids
            ):
                if not self.attachment_id:
                    pdf, _ = (
                        self.env["ir.actions.report"]
                        .sudo()
                        ._render_qweb_pdf(
                            "earlydryer_accounting_ng.action_report_daily_cash",
                            res_ids=branch.ids,
                            data={"date": str(self.date)},
                        )
                    )
                    self.sudo().attachment_id = (
                        self.env["ir.attachment"]
                        .sudo()
                        .create(
                            {
                                "name": f"daily-cash-{branch.code}-{self.date}.pdf",
                                "datas": base64.b64encode(pdf),
                                "mimetype": "application/pdf",
                                "res_model": self._name,
                                "res_id": self.id,
                            }
                        )
                    )
                rule._queue_email(
                    partner,
                    self.env._("Daily plant report"),
                    branch,
                    self.attachment_id,
                )
            if sub.whatsapp and partner not in branch.eod_whatsapp_recipient_ids:
                figures = branch.sudo()._earlydryer_eod_figures(self.date)
                self.env["earlydryer.notify.message"].notify(
                    "eod_report",
                    branch,
                    partner=partner,
                    context={
                        "staff_recipient": True,
                        "summary": f"Orders {figures['orders']}; sales {figures['sales_value']:.2f}",
                        "occurrence": f"eod-sub:{sub.id}:{self.date}",
                        "allowed_channels": ["whatsapp"],
                    },
                )
            sub.last_sent_on = self.date
        return result
