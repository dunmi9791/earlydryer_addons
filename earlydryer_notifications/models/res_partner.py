# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..tools import phone_e164


class ResPartner(models.Model):
    _inherit = "res.partner"
    earlydryer_notify_channel = fields.Selection(
        [("whatsapp", "WhatsApp"), ("sms", "SMS"), ("none", "None")],
        default="whatsapp",
        required=True,
    )
    earlydryer_notify_opt_out = fields.Boolean(string="No automatic order messages")
    earlydryer_notify_opt_in = fields.Boolean(
        string="Send order updates",
        help="I agree to receive order and payment updates by WhatsApp/SMS. Reply STOP to stop. Wording requires Earlydryer approval.",
    )
    earlydryer_notify_opt_out_on = fields.Datetime(readonly=True)
    earlydryer_notify_opt_out_source = fields.Char(readonly=True)
    earlydryer_whatsapp_unavailable = fields.Boolean(readonly=True)
    earlydryer_last_inbound_on = fields.Datetime(readonly=True)
    earlydryer_notify_phone = fields.Char(
        compute="_compute_notify_phone", store=True, index=True
    )

    @api.depends("phone")
    def _compute_notify_phone(self):
        for p in self:
            p.earlydryer_notify_phone = phone_e164(p.phone)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(v) for v in vals_list]
        for vals in vals_list:
            if "earlydryer_notify_opt_in" not in vals:
                vals["earlydryer_notify_opt_in"] = bool(phone_e164(vals.get("phone")))
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if not self.env.su and set(vals) & {
            "earlydryer_last_inbound_on",
            "earlydryer_whatsapp_unavailable",
            "earlydryer_notify_opt_out_on",
            "earlydryer_notify_opt_out_source",
        }:
            raise AccessError(
                self.env._(
                    "Messaging delivery and consent metadata is managed by the notification service."
                )
            )
        if "earlydryer_notify_opt_in" in vals:
            vals.update(
                earlydryer_notify_opt_out=not vals["earlydryer_notify_opt_in"],
                earlydryer_notify_opt_out_on=False
                if vals["earlydryer_notify_opt_in"]
                else fields.Datetime.now(),
                earlydryer_notify_opt_out_source="intake",
            )
        return super().write(vals)

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + [
            "earlydryer_notify_opt_in",
            "earlydryer_notify_opt_out",
            "earlydryer_notify_channel",
        ]
