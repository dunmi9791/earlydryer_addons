# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

from ..tools import phone_e164


class NotifyReplyWizard(models.TransientModel):
    _name = "earlydryer.notify.reply.wizard"
    _description = "Reply or Test Notification"
    inbound_id = fields.Many2one("earlydryer.notify.inbound")
    provider_id = fields.Many2one(
        "earlydryer.notify.provider", groups="earlydryer_base.group_admin"
    )
    phone = fields.Char()
    body = fields.Text()
    template_id = fields.Many2one(
        "earlydryer.notify.template", domain=[("approved", "=", True)]
    )

    def action_send(self):
        self.ensure_one()
        if self.inbound_id:
            self.inbound_id._check_reply_right()
            if not self.body and not self.template_id:
                raise UserError(self.env._("Enter a reply or select a template."))
            message = self.inbound_id.sudo()._reply(self.body or "", self.template_id)
            self.inbound_id.sudo().state = "replied"
        else:
            if not self.env.user.has_group("earlydryer_base.group_admin"):
                raise AccessError(
                    self.env._("Only Administrators can send test messages.")
                )
            provider = self.provider_id
            number = phone_e164(self.phone)
            if not provider or not number:
                raise UserError(
                    self.env._("Choose a provider and a valid international number.")
                )
            if (
                provider.channel == "whatsapp"
                and provider.provider_type != "log_only"
                and not self.template_id
            ):
                raise UserError(
                    self.env._("WhatsApp tests require an approved template.")
                )
            body, params = (
                self.template_id._render(provider, {})
                if self.template_id
                else (self.body, [])
            )
            message = (
                self.env["earlydryer.notify.message"]
                .sudo()
                .create(
                    {
                        "phone": number,
                        "provider_id": provider.id,
                        "channel": provider.channel,
                        "body": body,
                        "params_json": json.dumps(params),
                        "company_id": provider.company_id.id,
                        "template_id": self.template_id.id,
                        "meta_template_name": self.template_id.meta_template_name,
                        "meta_language": self.template_id.meta_language or "en",
                    }
                )
            )
            message._enqueue()
        return {"type": "ir.actions.act_window_close"}
