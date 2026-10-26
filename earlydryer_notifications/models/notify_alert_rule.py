# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..tools import LAGOS, phone_e164


class NotifyAlertRule(models.Model):
    _name = "earlydryer.notify.alert.rule"
    _description = "Notification Alert Rule"
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    event_id = fields.Many2one(
        "earlydryer.notify.event", required=True, domain=[("audience", "=", "staff")]
    )
    branch_ids = fields.Many2many("earlydryer.branch")
    threshold = fields.Float()
    mode = fields.Selection(
        [("immediate", "Immediate"), ("digest", "Digest")],
        default="immediate",
        required=True,
    )
    digest_times = fields.Char(default="10:00,15:00")
    recipient_group_ids = fields.Many2many("res.groups")
    recipient_user_ids = fields.Many2many("res.users")
    extra_phones = fields.Text(
        help="Comma-separated opted-in staff contact numbers. Each must match a contact with recorded consent."
    )
    channels = fields.Char(
        default="activity,whatsapp", help="Comma-separated: activity,email,whatsapp,sms"
    )
    last_digest_json = fields.Text(default="{}", readonly=True)

    @api.constrains("event_id", "threshold", "channels", "digest_times")
    def _check_rule(self):
        for rule in self:
            if rule.event_id.audience != "staff" or rule.threshold < 0:
                raise ValidationError(
                    self.env._(
                        "Alert events must be staff events with a nonnegative threshold."
                    )
                )
            if set((rule.channels or "").split(",")) - {
                "activity",
                "email",
                "whatsapp",
                "sms",
            }:
                raise ValidationError(self.env._("Unknown alert channel."))
            try:
                for t in (rule.digest_times or "").split(","):
                    h, m = map(int, t.strip().split(":"))
                    if not 0 <= h < 24 or not 0 <= m < 60:
                        raise ValueError()
            except ValueError:
                raise ValidationError(
                    self.env._("Digest times must be HH:MM separated by commas.")
                ) from None

    def _recipients(self, branch):
        users = self.recipient_user_ids | self.env["res.users"].search(
            [("group_ids", "in", self.recipient_group_ids.ids), ("share", "=", False)]
        )
        return users.filtered(
            lambda u: (
                u.active
                and (
                    branch in u.earlydryer_branch_ids
                    or u.has_group("earlydryer_base.group_all_branches")
                )
            )
        )

    @api.model
    def _dispatch(self, event, record, context):
        rules = self.search([("event_id", "=", event.id)])
        result = self.env["earlydryer.notify.message"]
        branch = result._branch(record)
        for rule in rules:
            if rule.branch_ids and branch not in rule.branch_ids:
                continue
            if rule.threshold > 0 and float(context.get("value", 0)) <= rule.threshold:
                continue
            occurrence = str(
                context.get(
                    "occurrence", getattr(record, "write_date", False) or record.id
                )
            )
            delivery = self.env["earlydryer.notify.alert"]._record_occurrence(
                rule, record, branch, context, occurrence
            )
            if delivery and rule.mode == "immediate":
                delivery.with_delay(
                    channel="root.earlydryer_notify",
                    identity_key=f"alert:{delivery.id}",
                )._deliver()
        return result

    def _deliver_to_recipients(self, record, branch, context):
        self.ensure_one()
        messages = self.env["earlydryer.notify.message"]
        users = self._recipients(branch)
        summary = context.get(
            "summary"
        ) or self.event_id.name + ": " + record.display_name + "; value " + str(
            context.get("value", "")
        )
        for user in users:
            if "activity" in self.channels and hasattr(record, "activity_schedule"):
                record.with_context(mail_notify_force_send=False).activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=user.id,
                    summary=self.event_id.name,
                    note=summary,
                )
            if "email" in self.channels and user.partner_id.email:
                self._queue_email(user.partner_id, summary, branch)
        partners = users.partner_id
        staff_phones = {
            user.partner_id.id: user.partner_id.phone or user.employee_id.mobile_phone
            for user in users
        }
        for number in (self.extra_phones or "").split(","):
            normalized = phone_e164(number)
            if normalized:
                extra_users = self.env["res.users"].search(
                    [
                        ("partner_id.earlydryer_notify_phone", "=", normalized),
                        ("partner_id.earlydryer_notify_opt_in", "=", True),
                        ("partner_id.earlydryer_notify_opt_out", "=", False),
                        ("share", "=", False),
                    ]
                )
                extra_users = extra_users.filtered(
                    lambda user: (
                        user.active
                        and (
                            branch in user.earlydryer_branch_ids
                            or user.has_group("earlydryer_base.group_all_branches")
                        )
                    )
                )
                partners |= extra_users.partner_id
        for partner in (
            partners
            if any(c in self.channels.split(",") for c in ("whatsapp", "sms"))
            else []
        ):
            ctx = dict(
                context,
                summary=summary,
                staff_recipient=True,
                allowed_channels=[
                    c for c in self.channels.split(",") if c in ("whatsapp", "sms")
                ],
            )
            message = messages._notify(
                self.event_id.code,
                record,
                partner=partner,
                phone=staff_phones.get(partner.id),
                context=ctx,
            )
            if message and message.channel not in self.channels.split(","):
                message.state = "cancelled"

    def _queue_email(self, partner, summary, branch, attachment=None):
        from markupsafe import Markup

        mail = self.env["mail.mail"].create(
            {
                "subject": self.event_id.name + " - " + (branch.name or "Earlydryer"),
                "body_html": str(Markup("<p>{}</p>").format(summary)),
                "email_to": partner.email,
                "email_from": branch.email
                or self.env.company.email
                or "earlydryer@localhost",
                "attachment_ids": [(4, attachment.id)] if attachment else [],
            }
        )
        self.with_delay(
            channel="root.earlydryer_notify", identity_key=f"notify-mail:{mail.id}"
        )._send_mail(mail.id)

    def _send_mail(self, mail_id):
        self.env["mail.mail"].browse(mail_id).exists().send(raise_exception=True)

    @api.model
    def _cron_digest(self):
        now = fields.Datetime.now().replace(tzinfo=ZoneInfo("UTC")).astimezone(LAGOS)
        for rule in self.search([("mode", "=", "digest")]):
            self.env.cr.execute(
                "SELECT id FROM earlydryer_notify_alert_rule WHERE id=%s FOR UPDATE",
                [rule.id],
            )
            rule.invalidate_recordset(["last_digest_json"])
            sent = json.loads(rule.last_digest_json or "{}")
            slots = sorted(
                t.strip()
                for t in rule.digest_times.split(",")
                if t.strip() <= now.strftime("%H:%M")
            )
            if not slots:
                continue
            slot = now.strftime("%Y-%m-%d") + " " + slots[-1]
            for branch in rule.branch_ids or self.env["earlydryer.branch"].search(
                [("active", "=", True)]
            ):
                if sent.get(str(branch.id), "") >= slot:
                    continue
                if rule.event_id.code == "alert_overdue":
                    jobs = self.env["laundry.job"].search(
                        [
                            ("earlydryer_branch_id", "=", branch.id),
                            ("is_overdue", "=", True),
                        ]
                    )
                    jobs = jobs.filtered(
                        lambda j: (
                            (fields.Datetime.now() - j.promised_on).total_seconds()
                            > rule.threshold * 3600
                        )
                    )
                    if jobs:
                        summary = "\n".join(
                            f"{j.name}: {j.partner_id.name}; {j.state}; {(fields.Datetime.now() - j.promised_on).total_seconds() / 3600:.1f} hours late"
                            for j in jobs
                        )
                        delivery = self.env[
                            "earlydryer.notify.alert"
                        ]._record_occurrence(
                            rule,
                            branch,
                            branch,
                            {"summary": summary, "occurrence": slot},
                            slot,
                        )
                        if delivery:
                            delivery.with_delay(
                                channel="root.earlydryer_notify",
                                identity_key=f"alert:{delivery.id}",
                            )._deliver()
                else:
                    pending = self.env["earlydryer.notify.alert"].search(
                        [
                            ("rule_id", "=", rule.id),
                            ("earlydryer_branch_id", "=", branch.id),
                            ("done", "=", False),
                        ]
                    )
                    if pending:
                        summary = "\n".join(
                            self.env[x.res_model].browse(x.res_id).display_name
                            for x in pending
                        )
                        delivery = self.env[
                            "earlydryer.notify.alert"
                        ]._record_occurrence(
                            rule,
                            branch,
                            branch,
                            {"summary": summary, "occurrence": slot},
                            slot,
                        )
                        if delivery:
                            delivery.with_delay(
                                channel="root.earlydryer_notify"
                            )._deliver()
                        pending.done = True
                sent[str(branch.id)] = slot
            rule.last_digest_json = json.dumps(sent)
