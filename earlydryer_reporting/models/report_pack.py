# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import json
import uuid

from odoo import Command, api, fields, models

from ..tools import DASHBOARD_GROUPS, has_any, scope


class ReportPack(models.Model):
    _name = "earlydryer.report.pack"
    _description = "Earlydryer Scheduled Report Pack"
    _order = "id desc"
    subscription_id = fields.Many2one(
        "earlydryer.report.subscription", required=True, ondelete="cascade", index=True
    )
    user_id = fields.Many2one(related="subscription_id.user_id", store=True)
    company_id = fields.Many2one(related="subscription_id.company_id", store=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    run_key = fields.Char(required=True, default="scheduled")
    state = fields.Selection(
        [("queued", "Queued"), ("done", "Done")], default="queued", required=True
    )
    data_json = fields.Text(readonly=True)
    attachment_ids = fields.Many2many("ir.attachment", readonly=True)
    mis_instance_ids = fields.Many2many("mis.report.instance", readonly=True)
    _period_unique = models.Constraint(
        "unique(subscription_id,date_from,date_to,run_key)",
        "This period is already scheduled.",
    )

    @api.model
    def _schedule(self, subscription, start, end, manual=False):
        subscription.check_access("read")
        key = str(uuid.uuid4()) if manual else "scheduled"
        self.env["earlydryer.notify.message"]._lock(
            f"pack:{subscription.id}:{start}:{end}:{key}"
        )
        old = self.sudo().search(
            [
                ("subscription_id", "=", subscription.id),
                ("date_from", "=", start),
                ("date_to", "=", end),
                ("run_key", "=", key),
            ],
            limit=1,
        )
        if old:
            return old
        pack = self.sudo().create(
            {
                "subscription_id": subscription.id,
                "date_from": start,
                "date_to": end,
                "run_key": key,
            }
        )
        pack.with_delay(
            channel="root.earlydryer_reporting", identity_key=f"report-pack:{pack.id}"
        )._deliver()
        return pack

    def _attachment(self, name, content, mimetype):
        return (
            self.env["ir.attachment"]
            .sudo()
            .create(
                {
                    "name": name,
                    "datas": base64.b64encode(content),
                    "mimetype": mimetype,
                    "res_model": self._name,
                    "res_id": self.id,
                }
            )
        )

    def _mis_reports(self, owner, branches):
        template = self.env.ref("earlydryer_accounting_ng.mis_report_pnl")
        instances = self.env["mis.report.instance"]
        plan = self.env.ref("earlydryer_accounting_ng.analytic_plan_service_lines")
        service_lines = self.env["account.analytic.account"].search(
            [
                ("plan_id", "=", plan.id),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.company_id.id),
            ]
        )
        for title, columns in [
            (self.env._("P&L by Plant"), branches.analytic_account_id),
            (self.env._("P&L by Service Line"), service_lines),
        ]:
            instance = (
                self.env["mis.report.instance"]
                .sudo()
                .create(
                    {
                        "name": title,
                        "report_id": template.id,
                        "company_id": self.company_id.id,
                        "date_from": self.date_from,
                        "date_to": self.date_to,
                        "target_move": "posted",
                        "earlydryer_report_branch_ids": [Command.set(branches.ids)],
                        "analytic_domain": repr(
                            [
                                (
                                    "analytic_distribution",
                                    "in",
                                    branches.analytic_account_id.ids,
                                )
                            ]
                        ),
                        "period_ids": [
                            Command.create(
                                {
                                    "name": col.name,
                                    "mode": "fix",
                                    "manual_date_from": self.date_from,
                                    "manual_date_to": self.date_to,
                                    "source": "actuals",
                                    "analytic_domain": repr(
                                        [("analytic_distribution", "in", [col.id])]
                                    ),
                                }
                            )
                            for col in columns
                        ]
                        + [
                            Command.create(
                                {
                                    "name": self.env._("Total"),
                                    "mode": "fix",
                                    "manual_date_from": self.date_from,
                                    "manual_date_to": self.date_to,
                                    "source": "actuals",
                                }
                            )
                        ],
                    }
                )
            )
            instance.with_user(owner).compute()
            pdf, _ = (
                self.env["ir.actions.report"]
                .with_user(owner)
                ._render_qweb_pdf(
                    "mis_builder.qweb_pdf_export",
                    res_ids=instance.ids,
                    data={"dummy": True},
                )
            )
            xlsx, _ = (
                self.env["ir.actions.report"]
                .with_user(owner)
                ._render_xlsx("mis_builder.xls_export", instance.ids, {"dummy": True})
            )
            self.attachment_ids = [
                Command.link(
                    self._attachment(title + ".pdf", pdf, "application/pdf").id
                ),
                Command.link(
                    self._attachment(
                        title + ".xlsx",
                        xlsx,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ).id
                ),
            ]
            instances |= instance
        self.mis_instance_ids = instances

    def _deliver(self):
        self.ensure_one()
        self = self.sudo()  # noqa: PLW0642 -- Queue delivery checks recipient scope below.
        self.env.cr.execute(
            "SELECT id FROM earlydryer_report_pack WHERE id=%s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset()
        if self.state == "done":
            return
        sub = self.subscription_id
        owner = sub.user_id or sub.owner_user_id
        scoped = self.with_user(owner).with_context(
            allowed_company_ids=[self.company_id.id]
        )
        staff_only = not has_any(scoped.env, DASHBOARD_GROUPS)
        branches = scope(scoped.env, sub.branch_ids.ids, staff=staff_only)
        kpis = scoped.env["earlydryer.kpi"].compute(
            [], branches.ids, self.date_from, self.date_to
        )
        self.data_json = json.dumps(kpis, default=str)
        pdf, _ = scoped.env["ir.actions.report"]._render_qweb_pdf(
            "earlydryer_reporting.action_pack_pdf", res_ids=self.ids
        )
        self.attachment_ids = [
            Command.link(
                self._attachment(
                    f"Earlydryer-{self.date_from}-{self.date_to}.pdf",
                    pdf,
                    "application/pdf",
                ).id
            )
        ]
        if sub.frequency == "monthly" and not staff_only:
            self._mis_reports(owner, branches)
        partner = sub.user_id.partner_id or sub.partner_id
        if sub.email and partner.email:
            from markupsafe import Markup

            rows = Markup("").join(
                Markup("<tr><td>{}</td><td>{:.2f}</td></tr>").format(
                    v["label"], v["value"]
                )
                for k, v in kpis.items()
                if not k.startswith("_")
            )
            mail = self.env["mail.mail"].create(
                {
                    "subject": self.env._(
                        "Earlydryer report %(start)s to %(end)s",
                        start=self.date_from,
                        end=self.date_to,
                    ),
                    "body_html": str(Markup("<table>{}</table>").format(rows)),
                    "email_to": partner.email,
                    "email_from": self.company_id.email or "earlydryer@localhost",
                    "attachment_ids": [Command.set(self.attachment_ids.ids)],
                }
            )
            self.with_delay(
                channel="root.earlydryer_reporting", identity_key=f"pack-mail:{mail.id}"
            )._send_mail(mail.id)
        if (
            sub.whatsapp
            and sub.frequency in ("weekly", "monthly")
            and branches
            and not staff_only
        ):
            summary = f"{self.date_from}–{self.date_to}: " + "; ".join(
                f"{v['label']}: {v['value']:.1f}"
                for k, v in kpis.items()
                if k in ("orders_value", "orders_count", "on_time_pct")
            )
            scoped.env["earlydryer.notify.message"].notify(
                "report_" + sub.frequency,
                branches[:1],
                partner=partner,
                context={
                    "staff_recipient": True,
                    "summary": summary,
                    "occurrence": f"pack:{self.id}",
                    "allowed_channels": ["whatsapp"],
                },
            )
        self.state = "done"
        sub.last_sent_on = fields.Date.context_today(
            self.with_context(tz="Africa/Lagos")
        )

    def _send_mail(self, mail_id):
        self.env["mail.mail"].browse(mail_id).exists().send(raise_exception=True)
