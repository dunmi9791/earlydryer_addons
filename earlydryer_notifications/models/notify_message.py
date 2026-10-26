# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import hashlib
import json
from datetime import timedelta

from markupsafe import Markup
from odoo import api, fields, models

from ..tools import phone_e164, quiet_eta

STATES = [
    (s, s.title())
    for s in (
        "queued",
        "held",
        "sending",
        "sent",
        "delivered",
        "read",
        "failed",
        "cancelled",
    )
]


class NotifyMessage(models.Model):
    _name = "earlydryer.notify.message"
    _description = "Notification Outbox"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    partner_id = fields.Many2one("res.partner", ondelete="set null")
    phone = fields.Char(index=True)
    channel = fields.Selection(
        [("whatsapp", "WhatsApp"), ("sms", "SMS")], required=True
    )
    provider_id = fields.Many2one("earlydryer.notify.provider", ondelete="restrict")
    event_id = fields.Many2one("earlydryer.notify.event", ondelete="restrict")
    template_id = fields.Many2one("earlydryer.notify.template", ondelete="set null")
    audience = fields.Selection(
        [("customer", "Customer"), ("staff", "Staff")],
        default="customer",
        required=True,
    )
    earlydryer_branch_id = fields.Many2one("earlydryer.branch", index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    res_model = fields.Char()
    res_id = fields.Many2oneReference(model_field="res_model")
    body = fields.Text()
    chatter_message_id = fields.Many2one(
        "mail.message", ondelete="set null", readonly=True
    )
    params_json = fields.Text(default="[]")
    render_context_json = fields.Text(default="{}")
    meta_template_name = fields.Char()
    meta_language = fields.Char(default="en")
    free_text = fields.Boolean()
    state = fields.Selection(STATES, default="queued", required=True, index=True)
    external_id = fields.Char(index=True, copy=False)
    error_code = fields.Char()
    error_message = fields.Text()
    attempts = fields.Integer(readonly=True)
    eta = fields.Datetime(readonly=True)
    sent_on = fields.Datetime()
    delivered_on = fields.Datetime()
    read_on = fields.Datetime()
    cost = fields.Float(digits=(16, 6))
    fallback_of_id = fields.Many2one("earlydryer.notify.message", copy=False)
    fallback_id = fields.Many2one("earlydryer.notify.message", copy=False)
    inbound_id = fields.Many2one("earlydryer.notify.inbound", ondelete="set null")
    occurrence = fields.Char(index=True)
    confirmation = fields.Boolean(
        help="STOP/START confirmation only; tied to an inbound record."
    )

    @api.model
    def _lock(self, key):
        lock = int.from_bytes(
            hashlib.sha256(key.encode()).digest()[:8], "big", signed=True
        )
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [lock])

    @api.model
    def notify(self, event_code, record, partner=None, phone=None, context=None):
        """Public integration API: errors are isolated from the business operation."""
        try:
            record.ensure_one()
            record.check_access("read")
            with self.env.cr.savepoint():
                return self.sudo()._notify(
                    event_code,
                    record.sudo(),
                    partner=partner,
                    phone=phone,
                    context=context or {},
                )
        except Exception:
            # Never expose template/provider/credential values through logs or callers.
            with self.env.cr.savepoint():
                try:
                    self.sudo()._diagnostic(event_code, record)
                except Exception:
                    return self.browse()
            return self.browse()

    @api.model
    def _diagnostic(self, event_code, record):
        event = self.env["earlydryer.notify.event"].search(
            [("code", "=", event_code)], limit=1
        )
        message = self.create(
            {
                "event_id": event.id,
                "channel": "sms",
                "state": "failed",
                "res_model": record._name,
                "res_id": record.id,
                "earlydryer_branch_id": self._branch(record).id,
                "error_code": "configuration",
                "error_message": "Notification configuration/rendering failed. Check template and provider settings.",
            }
        )
        message._admin_activity()
        return message

    @api.model
    def _branch(self, record):
        if "earlydryer_branch_id" in record._fields:
            return record.earlydryer_branch_id
        if record._name == "earlydryer.branch":
            return record
        if record._name == "pos.order":
            return record.config_id.earlydryer_branch_id
        if record._name == "account.payment":
            invoices = record.invoice_ids | record.reconciled_invoice_ids
            branches = (
                invoices.earlydryer_branch_id
                if "earlydryer_branch_id" in invoices._fields
                else self.env["earlydryer.branch"]
            )
            return branches[:1] or self.env["earlydryer.branch"].search(
                [("cash_journal_id", "=", record.journal_id.id)], limit=1
            )
        return self.env["earlydryer.branch"]

    @api.model
    def _phone_opted_out(self, phone, company):
        command = self.env["earlydryer.notify.inbound"].search(
            [
                ("phone", "=", phone),
                ("company_id", "=", company.id),
                ("command", "!=", False),
            ],
            order="received_on desc,id desc",
            limit=1,
        )
        return command.command == "stop"

    @api.model
    def _notify(self, code, record, partner=None, phone=None, context=None):
        context = context or {}
        event = self.env["earlydryer.notify.event"].search(
            [("code", "=", code)], limit=1
        )
        branch = self._branch(record)
        if not event or (event.branch_ids and branch not in event.branch_ids):
            return self.browse()
        if event.audience == "staff" and not context.get("staff_recipient"):
            return self.env["earlydryer.notify.alert.rule"]._dispatch(
                event, record, context
            )
        partner = (
            partner
            or (
                record.partner_id
                if "partner_id" in record._fields
                else self.env["res.partner"]
            )
        ).sudo()
        number = phone_e164(phone or partner.phone)
        if not number or (
            partner
            and (
                partner.earlydryer_notify_opt_out
                or not partner.earlydryer_notify_opt_in
                or partner.earlydryer_notify_channel == "none"
            )
        ):
            return self.browse()
        channels = event.channels.split(",")
        if context.get("allowed_channels"):
            channels = [c for c in channels if c in context["allowed_channels"]]
        if partner and partner.earlydryer_notify_channel == "sms":
            channels = [c for c in channels if c == "sms"]
        if partner and partner.earlydryer_whatsapp_unavailable:
            channels = [c for c in channels if c != "whatsapp"]
        if self._phone_opted_out(number, branch.company_id or self.env.company):
            return self.browse()
        if not channels:
            return self.browse()
        occurrence = str(context.get("occurrence", ""))
        key = f"{code}:{record._name}:{record.id}:{number}"
        self._lock(key)
        domain = [
            ("event_id", "=", event.id),
            ("res_model", "=", record._name),
            ("res_id", "=", record.id),
            ("phone", "=", number),
            ("fallback_of_id", "=", False),
        ]
        if occurrence:
            duplicate = self.search(domain + [("occurrence", "=", occurrence)], limit=1)
            if duplicate:
                return duplicate
        existing = self.search(domain, limit=1)
        if existing:
            # A repeated job state needs explicit allow_repeat and a new state-transition occurrence.
            if (
                code.startswith("job_")
                and code != "job_creation_failed"
                and not event.allow_repeat
            ):
                return existing
            if (
                not event.allow_repeat
                and existing.create_date
                >= fields.Datetime.now() - timedelta(minutes=event.dedupe_minutes)
            ):
                return existing
        return self._prepare(
            event, record, partner, number, branch, channels[0], context, occurrence
        )

    @api.model
    def _prepare(
        self, event, record, partner, phone, branch, channel, context, occurrence=""
    ):
        company = branch.company_id or (
            record.company_id if "company_id" in record._fields else self.env.company
        )
        provider = self.env["earlydryer.notify.provider"].search(
            [("company_id", "=", company.id), ("channel", "=", channel)], limit=1
        )
        templates = self.env["earlydryer.notify.template"].search(
            [
                ("event_id", "=", event.id),
                ("channel", "=", channel),
                "|",
                ("branch_id", "=", branch.id),
                ("branch_id", "=", False),
            ]
        )
        template = (
            templates.filtered(lambda t: t.branch_id == branch)[:1]
            or templates.filtered(lambda t: not t.branch_id)[:1]
        )
        ctx = self._render_context(record, branch, context)
        body, params = template._render(record, ctx) if template else ("", [])
        eta = None
        if event.audience == "customer" and not event.urgent:
            config = self.env["ir.config_parameter"].sudo()
            start = float(config.get_param("earlydryer_notify.quiet_start", 21))
            end = float(config.get_param("earlydryer_notify.quiet_end", 7))
            eta = quiet_eta(fields.Datetime.now(), start, end)
        message = self.create(
            {
                "partner_id": partner.id,
                "phone": phone,
                "channel": channel,
                "provider_id": provider.id,
                "event_id": event.id,
                "template_id": template.id,
                "audience": event.audience,
                "earlydryer_branch_id": branch.id,
                "company_id": company.id,
                "res_model": record._name,
                "res_id": record.id,
                "body": body,
                "params_json": json.dumps(params),
                "render_context_json": json.dumps(context),
                "occurrence": occurrence,
                "meta_template_name": template.meta_template_name,
                "meta_language": template.meta_language or "en",
                "eta": eta,
                "state": "held" if eta else "queued",
            }
        )
        if (
            not provider
            or not template
            or (
                channel == "whatsapp"
                and provider.provider_type != "log_only"
                and (not template.approved or not template.meta_template_name)
            )
        ):
            message.write(
                {
                    "state": "failed",
                    "error_code": "configuration",
                    "error_message": "Missing provider, template or WhatsApp approval.",
                }
            )
            message._admin_activity()
        else:
            message._enqueue(eta)
        return message

    @api.model
    def _render_context(self, record, branch, extra):
        ctx = {
            "plant": branch.name or "Earlydryer",
            "plant_phone": branch.phone or "Contact the plant",
            "number": record.display_name,
            "state": getattr(record, "state", ""),
            "shelf": getattr(getattr(record, "shelf_id", False), "name", "")
            or "Ask at reception",
            "hours": branch.resource_calendar_id.name
            or "Contact the plant for opening hours",
            "promised": str(getattr(record, "promised_on", "") or "To be confirmed"),
            "items": getattr(record, "item_count", 0),
            "amount": getattr(record, "amount_total", getattr(record, "amount", 0)),
            "balance": getattr(record, "amount_due", 0),
            "wallet_balance": getattr(
                getattr(record, "wallet_id", False), "balance", 0
            ),
            "days_left": 0,
            "summary": "",
        }
        ctx.update(extra)
        return ctx

    def _enqueue(self, eta=None):
        self.ensure_one()
        self.with_delay(
            channel="root.earlydryer_notify",
            identity_key=f"notify:{self.id}:{self.attempts}",
            eta=eta,
            max_retries=5,
        )._send()

    def _admin_activity(self):
        group = self.env.ref("earlydryer_base.group_admin")
        users = self.env["res.users"].search(
            [("group_ids", "in", [group.id]), ("share", "=", False)]
        )
        for user in users:
            self.with_context(mail_notify_force_send=False).activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary=self.env._("Notification needs attention"),
                note=self.env._(
                    "Check the failed notification and configuration. No business operation was stopped."
                ),
            )

    def _send(self):
        self.ensure_one()
        self = self.sudo()
        self.env.cr.execute(
            "SELECT id FROM earlydryer_notify_message WHERE id=%s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset()
        if self.state not in ("queued", "held"):
            return
        now = fields.Datetime.now()
        if self.eta and self.eta > now:
            self._enqueue(self.eta)
            return
        partner = self.partner_id
        if self._phone_opted_out(self.phone, self.company_id) and not self.confirmation:
            self.state = "cancelled"
            return
        if (
            partner
            and (
                partner.earlydryer_notify_opt_out
                or not partner.earlydryer_notify_opt_in
            )
            and not self.confirmation
        ):
            self.state = "cancelled"
            return
        if self.free_text and self.channel == "whatsapp":
            last = max(
                filter(
                    None,
                    [self.inbound_id.received_on, partner.earlydryer_last_inbound_on],
                ),
                default=False,
            )
            if not last or last < now - timedelta(hours=24):
                self.write(
                    {
                        "state": "failed",
                        "error_code": "window_expired",
                        "error_message": "Choose an approved WhatsApp template outside the 24-hour window.",
                    }
                )
                return
        if not self.provider_id or not self.provider_id.active:
            self.write({"state": "failed", "error_code": "provider_disabled"})
            self._admin_activity()
            return
        if not self.provider_id._take_rate_slot(now):
            self.eta = now + timedelta(minutes=1)
            self._enqueue(self.eta)
            return
        self.write({"state": "sending", "attempts": self.attempts + 1})
        try:
            adapter = self.provider_id._adapter()
            result = (
                adapter.send_text(self)
                if self.channel == "sms" or self.free_text
                else adapter.send_template(self)
            )
        except Exception:
            # Provider implementations may raise. The outbox must still record an attempt.
            from ..providers import SendResult

            result = SendResult(
                False,
                error_code="adapter_error",
                error_message="Provider adapter failed",
                retryable=True,
            )
        if result.ok:
            self.write(
                {
                    "state": "sent",
                    "external_id": result.external_id,
                    "sent_on": now,
                    "cost": result.cost,
                    "error_code": False,
                    "error_message": False,
                }
            )
            record = (
                self.env[self.res_model].browse(self.res_id).exists()
                if self.res_model and self.res_id
                else False
            )
            if record and hasattr(record, "message_post"):
                posted = record.with_context(mail_notify_force_send=False).message_post(
                    body=Markup("<p>{}: {}</p>").format(
                        self.env._("Customer message"), self.body or ""
                    ),
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                    partner_ids=[],
                )
                self.chatter_message_id = posted
            return
        self.write(
            {"error_code": result.error_code, "error_message": result.error_message}
        )
        if result.retryable and self.attempts < 5:
            # Persist counters and schedule a new job; raising RetryableJobError would roll them back.
            eta = now + timedelta(minutes=[1, 5, 15, 60][self.attempts - 1])
            self.write({"state": "queued", "eta": eta})
            self._enqueue(eta)
            return
        self.state = "failed"
        if result.error_code in ("131050", "opted_out"):
            partner.write(
                {
                    "earlydryer_notify_opt_in": False,
                    "earlydryer_notify_opt_out_source": "provider",
                }
            )
        if result.error_code in ("131026", "not_on_whatsapp"):
            partner.earlydryer_whatsapp_unavailable = True
        if not result.retryable:
            self._fallback()
        self._admin_activity()

    def _fallback(self):
        self.ensure_one()
        if (
            self.channel != "whatsapp"
            or self.fallback_id
            or "sms" not in (self.event_id.channels or "").split(",")
        ):
            return
        if self.partner_id and (
            self.partner_id.earlydryer_notify_opt_out
            or self.partner_id.earlydryer_notify_channel == "none"
        ):
            return
        record = (
            self.env[self.res_model].browse(self.res_id).exists()
            if self.res_model and self.res_id
            else False
        )
        if record:
            fallback = self._prepare(
                self.event_id,
                record,
                self.partner_id,
                self.phone,
                self.earlydryer_branch_id,
                "sms",
                json.loads(self.render_context_json or "{}"),
                self.occurrence,
            )
            fallback.fallback_of_id = self
            self.fallback_id = fallback

    @api.model
    def _cron_retention(self):
        days = max(
            1,
            int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("earlydryer_notify.retention_days", 365)
            ),
        )
        cutoff = fields.Datetime.now() - timedelta(days=days)
        old = self.sudo().search([("create_date", "<", cutoff)])
        old.chatter_message_id.sudo().write(
            {"body": "<p>Notification body removed by retention.</p>"}
        )
        old.write(
            {
                "body": False,
                "params_json": False,
                "render_context_json": False,
                "error_message": False,
            }
        )
        self.env["earlydryer.notify.inbound"].sudo().search(
            [("received_on", "<", cutoff)]
        ).write({"body": False, "media": False})
        self.env["earlydryer.notify.webhook.log"].sudo().search(
            [("create_date", "<", fields.Datetime.now() - timedelta(days=30))]
        ).unlink()
