# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json
import re
import secrets
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..providers import adapter_for

ADMIN = "earlydryer_base.group_admin"


class NotifyProvider(models.Model):
    _name = "earlydryer.notify.provider"
    _description = "Notification Provider"
    _order = "sequence, id"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    channel = fields.Selection(
        [("whatsapp", "WhatsApp"), ("sms", "SMS")], required=True
    )
    provider_type = fields.Selection(
        [
            ("meta_cloud", "Meta Cloud API"),
            ("generic_http", "Generic HTTP"),
            ("log_only", "Log only"),
        ],
        required=True,
        default="log_only",
    )
    api_token = fields.Char(groups=ADMIN, copy=False)
    app_secret = fields.Char(groups=ADMIN, copy=False)
    webhook_verify_token = fields.Char(groups=ADMIN, copy=False)
    path_token = fields.Char(
        default=lambda self: secrets.token_urlsafe(32),
        groups=ADMIN,
        copy=False,
        readonly=True,
    )
    phone_number_id = fields.Char()
    business_account_id = fields.Char()
    # Deliberately no guessed current version: official Meta docs were inaccessible during development.
    graph_version = fields.Char(
        help="Supported Graph API version, e.g. v23.0. Verify in Meta's current documentation before activation."
    )
    default_language = fields.Char(default="en")
    http_method = fields.Selection(
        [("POST", "POST"), ("PUT", "PUT")], default="POST", required=True
    )
    url_template = fields.Char(
        help="HTTPS only. Termii, BulkSMSNigeria and Africa's Talking are examples; no gateway is selected."
    )
    headers_json = fields.Text(
        default='{"Authorization": "Bearer {api_token}"}', groups=ADMIN
    )
    body_template = fields.Text(
        default='{"to":"{to}","from":"{sender}","text":"{text}"}', groups=ADMIN
    )
    body_encoding = fields.Selection(
        [("json", "JSON"), ("form", "Form")], default="json", required=True
    )
    success_json_path = fields.Char()
    message_id_json_path = fields.Char(default="id")
    error_json_path = fields.Char()
    cost_json_path = fields.Char()
    sender_id = fields.Char(size=11)
    webhook_url = fields.Char(compute="_compute_webhook_url", groups=ADMIN)
    rate_limit_per_minute = fields.Integer(default=60, required=True)
    rate_minute = fields.Datetime(readonly=True)
    rate_count = fields.Integer(readonly=True)

    @api.depends("path_token")
    def _compute_webhook_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for p in self:
            p.webhook_url = (
                f"{base}/earlydryer/notify/webhook/{p.id}/{p.path_token}"
                if p.id
                else False
            )

    @api.constrains(
        "provider_type",
        "channel",
        "url_template",
        "headers_json",
        "body_template",
        "graph_version",
        "rate_limit_per_minute",
    )
    def _check_config(self):
        for p in self:
            if p.rate_limit_per_minute < 1:
                raise ValidationError(self.env._("Rate limit must be positive."))
            if p.provider_type == "meta_cloud" and (
                p.channel != "whatsapp"
                or not re.fullmatch(r"v[0-9]+\.0", p.graph_version or "")
            ):
                raise ValidationError(
                    self.env._(
                        "Meta requires WhatsApp and an explicitly selected Graph API version."
                    )
                )
            if p.provider_type == "generic_http":
                u = urlsplit(p.url_template or "")
                if u.scheme != "https" or not u.hostname or u.username or u.password:
                    raise ValidationError(
                        self.env._(
                            "The gateway URL must use HTTPS without embedded credentials."
                        )
                    )
                for value in [p.headers_json, p.body_template]:
                    try:
                        if not isinstance(json.loads(value or "{}"), dict):
                            raise ValueError()
                    except (ValueError, TypeError):
                        raise ValidationError(
                            self.env._("Gateway headers and body must be JSON objects.")
                        ) from None

    def _adapter(self):
        self.ensure_one()
        return adapter_for(self)

    def action_test_connection(self):
        self.check_access("write")
        self._check_config()
        # Queue the harmless check; no HTTP in the user's transaction.
        self.with_delay(channel="root.earlydryer_notify")._test_connection()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": self.env._(
                    "Configuration checked; connection check queued."
                ),
                "type": "success",
            },
        }

    def _test_connection(self):
        self.ensure_one()
        if self.provider_type == "meta_cloud":
            p = self.sudo()
            code, _ = p._adapter()._request(
                "GET",
                f"https://graph.facebook.com/{p.graph_version}/{p.phone_number_id}",
                headers={"Authorization": "Bearer " + (p.api_token or "")},
            )
            if not 200 <= code < 300:
                raise ValidationError(
                    self.env._(
                        "Meta connection check failed. Check credentials and version."
                    )
                )
        return True

    def action_send_test(self):
        self.check_access("write")
        return {
            "type": "ir.actions.act_window",
            "res_model": "earlydryer.notify.reply.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_provider_id": self.id},
        }

    def _take_rate_slot(self, now):
        self.env.cr.execute(
            "SELECT id FROM earlydryer_notify_provider WHERE id=%s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(["rate_minute", "rate_count"])
        minute = now.replace(second=0, microsecond=0)
        count = self.rate_count if self.rate_minute == minute else 0
        if count >= self.rate_limit_per_minute:
            return False
        self.write({"rate_minute": minute, "rate_count": count + 1})
        return True
