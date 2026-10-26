# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..tools import phone_e164


class NotifyInbound(models.Model):
    _name = "earlydryer.notify.inbound"
    _description = "Notification Inbox"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "received_on desc, id desc"
    provider_id = fields.Many2one(
        "earlydryer.notify.provider", required=True, ondelete="restrict"
    )
    channel = fields.Selection(
        [("whatsapp", "WhatsApp"), ("sms", "SMS")], required=True
    )
    phone = fields.Char(required=True, index=True)
    partner_id = fields.Many2one("res.partner", ondelete="set null")
    body = fields.Text()
    command = fields.Selection(
        [("stop", "STOP"), ("start", "START")], readonly=True, index=True
    )
    media = fields.Char(help="Provider media reference only; never downloaded.")
    received_on = fields.Datetime(default=fields.Datetime.now, required=True)
    external_id = fields.Char(required=True, index=True)
    earlydryer_branch_id = fields.Many2one("earlydryer.branch", index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    assigned_user_id = fields.Many2one("res.users")
    state = fields.Selection(
        [
            (s, s.replace("_", " ").title())
            for s in ("auto_replied", "needs_reply", "replied", "closed")
        ],
        default="needs_reply",
        required=True,
        index=True,
    )
    _external_unique = models.Constraint(
        "unique(provider_id, external_id)", "Inbound message already received."
    )

    @api.model
    def _receive(self, provider, event):
        if not event.external_id:
            return self.browse()
        number = phone_e164(
            event.phone if str(event.phone).startswith("+") else "+" + str(event.phone)
        )
        if not number:
            return self.browse()
        self.env["earlydryer.notify.message"]._lock(
            f"inbound:{provider.id}:{event.external_id}"
        )
        existing = self.search(
            [
                ("provider_id", "=", provider.id),
                ("external_id", "=", event.external_id),
            ],
            limit=1,
        )
        if existing:
            return existing
        partners = self.env["res.partner"].search(
            [
                ("earlydryer_notify_phone", "=", number),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", provider.company_id.id),
            ]
        )
        jobs = self.env["laundry.job"].search(
            [
                ("partner_id", "in", partners.ids),
                ("company_id", "=", provider.company_id.id),
            ],
            order="received_on desc,id desc",
        )
        partner = jobs[:1].partner_id or partners[:1]
        received = fields.Datetime.now()
        if event.received_on:
            try:
                received = min(
                    received, datetime.utcfromtimestamp(int(event.received_on))
                )
            except (ValueError, OverflowError, TypeError, OSError):
                received = fields.Datetime.now()
        inbound = self.create(
            {
                "provider_id": provider.id,
                "channel": provider.channel,
                "phone": number,
                "partner_id": partner.id,
                "body": event.body[:10000],
                "command": event.body.strip().lower()
                if event.body.strip().lower() in ("stop", "start")
                else False,
                "media": event.media,
                "received_on": received,
                "external_id": event.external_id,
                "earlydryer_branch_id": jobs[:1].earlydryer_branch_id.id,
                "company_id": provider.company_id.id,
            }
        )
        if partner and (
            not partner.earlydryer_last_inbound_on
            or received > partner.earlydryer_last_inbound_on
        ):
            partner.earlydryer_last_inbound_on = received
        inbound._bot()
        return inbound

    def write(self, vals):
        if not self.env.su:
            self._check_reply_right()
            if set(vals) - {"assigned_user_id", "state"}:
                raise AccessError(
                    self.env._("Inbox content and customer identity cannot be changed.")
                )
            if vals.get("assigned_user_id"):
                user = self.env["res.users"].browse(vals["assigned_user_id"])
                for inbound in self:
                    if (
                        inbound.earlydryer_branch_id
                        and inbound.earlydryer_branch_id
                        not in user.earlydryer_branch_ids
                        and not user.has_group("earlydryer_base.group_all_branches")
                    ):
                        raise AccessError(self.env._("Assign a user of this plant."))
        return super().write(vals)

    def _check_reply_right(self):
        if not any(
            self.env.user.has_group("earlydryer_base." + g)
            for g in (
                "group_customer_service",
                "group_branch_manager",
                "group_management",
                "group_admin",
            )
        ):
            raise AccessError(
                self.env._("Only Customer Service and managers can reply.")
            )
        self.check_access("write")

    def action_assign_to_me(self):
        self._check_reply_right()
        self.write({"assigned_user_id": self.env.uid})

    def action_close(self):
        self._check_reply_right()
        self.write({"state": "closed"})

    def action_reply(self):
        self._check_reply_right()
        return {
            "type": "ir.actions.act_window",
            "res_model": "earlydryer.notify.reply.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_inbound_id": self.id},
        }

    def action_open_jobs(self):
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "res_model": "laundry.job",
            "view_mode": "list,form",
            "domain": [
                ("partner_id", "=", self.partner_id.id),
                ("state", "not in", ["collected", "delivered", "cancelled"]),
            ],
        }

    def action_open_messages(self):
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "res_model": "earlydryer.notify.message",
            "view_mode": "list,form",
            "domain": [("phone", "=", self.phone)],
        }

    def _reply(self, body, template=None, confirmation=False):
        self.ensure_one()
        now = fields.Datetime.now()
        last_inbound = max(
            self.received_on,
            self.partner_id.earlydryer_last_inbound_on or self.received_on,
        )
        if (
            self.channel == "whatsapp"
            and not template
            and last_inbound < now - timedelta(hours=24)
        ):
            raise UserError(
                self.env._("Select an approved template outside the 24-hour window.")
            )
        partner = self.partner_id
        if partner and partner.earlydryer_notify_opt_out and not confirmation:
            raise UserError(self.env._("The customer has opted out."))
        if template and (
            template.channel != self.channel
            or not template.approved
            or (template.branch_id and template.branch_id != self.earlydryer_branch_id)
        ):
            raise UserError(
                self.env._("Select an approved template for this channel and plant.")
            )
        params = []
        if template:
            body, params = template._render(
                self,
                self.env["earlydryer.notify.message"]._render_context(
                    self, self.earlydryer_branch_id, {}
                ),
            )
        import json

        message = self.env["earlydryer.notify.message"].create(
            {
                "partner_id": partner.id,
                "phone": self.phone,
                "provider_id": self.provider_id.id,
                "channel": self.channel,
                "inbound_id": self.id,
                "earlydryer_branch_id": self.earlydryer_branch_id.id,
                "company_id": self.company_id.id,
                "body": body,
                "free_text": not bool(template),
                "template_id": template.id if template else False,
                "meta_template_name": template.meta_template_name
                if template
                else False,
                "meta_language": template.meta_language if template else "en",
                "params_json": json.dumps(params),
                "confirmation": confirmation,
            }
        )
        message._enqueue()
        return message

    def _needs_reply(self):
        self.state = "needs_reply"
        branch = self.earlydryer_branch_id
        group = self.env.ref("earlydryer_base.group_customer_service")
        users = self.env["res.users"].search(
            [("group_ids", "in", [group.id]), ("share", "=", False)]
        )
        users = users.filtered(
            lambda u: (
                (branch in u.earlydryer_branch_ids)
                if branch
                else u.has_group("earlydryer_base.group_all_branches")
            )
        )
        users = users or branch.manager_id or self.env.ref("base.user_admin")
        for user in users:
            self.with_context(mail_notify_force_send=False).activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary=self.env._("Customer message needs a reply"),
            )
        cutoff = fields.Datetime.now() - timedelta(hours=4)
        messages = self.env["earlydryer.notify.message"]
        messages._lock("ack:" + self.phone)
        if not messages.search_count(
            [
                ("phone", "=", self.phone),
                ("inbound_id", "!=", False),
                ("body", "=", self._ack_text()),
                ("create_date", ">=", cutoff),
            ]
        ):
            if not self.partner_id.earlydryer_notify_opt_out and (
                self.channel != "whatsapp"
                or self.received_on >= fields.Datetime.now() - timedelta(hours=24)
            ):
                self._reply(self._ack_text())

    def _ack_text(self):
        return self.env._("Thank you. A member of our team will reply shortly.")

    def _bot(self):
        self.ensure_one()
        text = (self.body or "").strip().lower()
        partner = self.partner_id
        if text in ("stop", "start"):
            partner.write(
                {
                    "earlydryer_notify_opt_in": text == "start",
                    "earlydryer_notify_opt_out_source": "inbound_" + self.channel,
                }
            )
            self._reply(
                self.env._("Order updates stopped. Reply START to resume.")
                if text == "stop"
                else self.env._("Order updates resumed. Reply STOP to stop."),
                confirmation=True,
            )
            self.state = "auto_replied"
            return
        if (
            self.channel != "whatsapp"
            or not partner
            or partner.earlydryer_notify_opt_out
        ):
            self._needs_reply()
            return
        partners = self.env["res.partner"].search(
            [("earlydryer_notify_phone", "=", self.phone)]
        )
        jobs = self.env["laundry.job"].search(
            [
                ("partner_id", "in", partners.ids),
                ("company_id", "=", self.company_id.id),
            ]
        )
        reply = False
        if text in ("status", "track", "where is my order"):
            open_jobs = jobs.filtered(
                lambda j: j.state not in ("collected", "delivered", "cancelled")
            )[:5]
            reply = "\n".join(self._job_text(job) for job in open_jobs) or self.env._(
                "You have no open orders. Contact your plant if you need help."
            )
        elif text == "balance":
            wallets = self.env["earlydryer.wallet"].search(
                [
                    ("partner_id", "in", partners.commercial_partner_id.ids),
                    ("company_id", "=", self.company_id.id),
                ]
            )
            reply = self.env._(
                "Wallet balance: %(amount).2f. %(plant)s %(phone)s",
                amount=sum(wallets.mapped("balance")),
                plant=self.earlydryer_branch_id.name or "Earlydryer",
                phone=self.earlydryer_branch_id.phone or "",
            )
        elif text in ("help", "menu"):
            branches = self.env["earlydryer.branch"].search(
                [("company_id", "=", self.company_id.id)]
            )
            reply = (
                self.env._(
                    "Send STATUS, a job number, a garment tag, BALANCE, STOP or START."
                )
                + "\n"
                + "\n".join(f"{b.name}: {b.phone or ''}" for b in branches)
            )
        else:
            job = jobs.filtered(lambda j: j.name.upper() == text.upper())[:1]
            if not job and self.env["earlydryer.tag.code"].is_valid(text):
                item = self.env["laundry.job.item"].search(
                    [("tag_code", "=", text.upper()), ("job_id", "in", jobs.ids)],
                    limit=1,
                )
                job = item.job_id
            if job:
                reply = self._job_text(job)
        if reply:
            self._reply(reply)
            self.state = "auto_replied"
        else:
            self._needs_reply()

    def _job_text(self, job):
        labels = {
            "ironing": "being ironed",
            "washing": "being washed",
            "ready": "ready for collection",
            "received": "received",
        }
        state = labels.get(
            job.state,
            dict(job._fields["state"]._description_selection(self.env)).get(
                job.state, job.state
            ),
        )
        if job.state == "ready":
            state += (
                f" at {job.earlydryer_branch_id.name}, shelf {job.shelf_id.name or '-'}"
            )
        return f"{job.name}: {job.earlydryer_branch_id.name}; {state}; promised {job.promised_on or '-'}; due {job.amount_due:.2f}; {job.earlydryer_branch_id.phone or ''}"
