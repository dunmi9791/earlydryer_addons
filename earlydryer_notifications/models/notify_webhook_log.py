# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json

from odoo import fields, models

from ..providers import adapter_for


class NotifyWebhookLog(models.Model):
    _name = "earlydryer.notify.webhook.log"
    _description = "Notification Webhook Receipt"
    _order = "id desc"
    provider_id = fields.Many2one(
        "earlydryer.notify.provider", required=True, ondelete="cascade"
    )
    payload = fields.Text(required=True)
    processed = fields.Boolean(readonly=True)
    error = fields.Char(readonly=True)

    def _process(self):
        self.ensure_one()
        self = self.sudo()
        self.env.cr.execute(
            "SELECT id FROM earlydryer_notify_webhook_log WHERE id=%s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()
        if self.processed:
            return
        provider = self.provider_id
        events = adapter_for(provider).parse_webhook(json.loads(self.payload), {})
        for event in events:
            if event.kind == "inbound":
                self.env["earlydryer.notify.inbound"]._receive(provider, event)
            elif event.kind == "status" and event.external_id:
                messages = self.env["earlydryer.notify.message"].search(
                    [
                        ("provider_id", "=", provider.id),
                        ("external_id", "=", event.external_id),
                    ]
                )
                for message in messages:
                    self.env.cr.execute(
                        "SELECT id FROM earlydryer_notify_message WHERE id=%s FOR UPDATE",
                        [message.id],
                    )
                    message.invalidate_recordset()
                    rank = {
                        "queued": 0,
                        "held": 0,
                        "sending": 0,
                        "sent": 1,
                        "failed": 1,
                        "delivered": 2,
                        "read": 3,
                        "cancelled": 4,
                    }
                    if event.state not in ("sent", "delivered", "read", "failed") or (
                        rank[event.state] <= rank[message.state]
                        and not (event.state == "failed" and message.state == "sent")
                    ):
                        continue
                    vals = {"state": event.state}
                    if event.state == "delivered":
                        vals["delivered_on"] = fields.Datetime.now()
                    if event.state == "read":
                        vals["read_on"] = fields.Datetime.now()
                    if event.state == "failed":
                        vals.update(
                            error_code=event.error_code,
                            error_message="Provider delivery failed",
                        )
                    message.write(vals)
                    if event.state == "failed":
                        if event.error_code in ("131026", "not_on_whatsapp"):
                            message.partner_id.earlydryer_whatsapp_unavailable = True
                        if event.error_code in ("131050", "opted_out"):
                            message.partner_id.write(
                                {
                                    "earlydryer_notify_opt_in": False,
                                    "earlydryer_notify_opt_out_source": "provider",
                                }
                            )
                        message._fallback()
        self.processed = True
