# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..tools import DASHBOARD_GROUPS, LAGOS, has_any, scope


class ReportSubscription(models.Model):
    _name = "earlydryer.report.subscription"
    _description = "Earlydryer Report Subscription"
    _rec_name = "user_id"
    user_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, index=True
    )
    partner_id = fields.Many2one(
        "res.partner",
        help="Email-only recipient without a login; Management must configure explicit plants.",
    )
    owner_user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, readonly=True
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    frequency = fields.Selection(
        [
            ("daily", "Daily (merged EOD)"),
            ("weekly", "Weekly (Monday)"),
            ("monthly", "Monthly (1st)"),
        ],
        required=True,
        default="weekly",
    )
    send_time = fields.Float(
        default=8,
        help="Lagos time. Daily subscriptions use the plant EOD time instead.",
    )
    branch_ids = fields.Many2many("earlydryer.branch")
    email = fields.Boolean(default=True)
    whatsapp = fields.Boolean()
    active = fields.Boolean(default=True)
    last_sent_on = fields.Date(readonly=True, copy=False)

    @api.constrains(
        "user_id", "partner_id", "branch_ids", "send_time", "company_id", "whatsapp"
    )
    def _check_subscription(self):
        for sub in self:
            if bool(sub.user_id) == bool(sub.partner_id) or not 0 <= sub.send_time < 24:
                raise ValidationError(
                    self.env._(
                        "Select one user or one email-only contact, and a valid send time."
                    )
                )
            if sub.partner_id and (not sub.branch_ids or sub.whatsapp):
                raise ValidationError(
                    self.env._(
                        "Contacts without a login require explicit plants and email only."
                    )
                )
            if sub.branch_ids.company_id - sub.company_id:
                raise ValidationError(
                    self.env._("Choose plants of the subscription company.")
                )
            owner = sub.user_id or sub.owner_user_id
            allowed = scope(
                sub.with_user(owner)
                .with_context(allowed_company_ids=[sub.company_id.id])
                .env,
                sub.branch_ids.ids,
                staff=not has_any(sub.with_user(owner).env, DASHBOARD_GROUPS),
            )
            if sub.branch_ids and set(allowed.ids) != set(sub.branch_ids.ids):
                raise AccessError(
                    self.env._("The recipient cannot access those plants.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        if not has_any(self.env, ("group_management", "group_admin")):
            for vals in vals_list:
                if (
                    vals.get("partner_id")
                    or vals.get("user_id", self.env.uid) != self.env.uid
                    or vals.get("owner_user_id", self.env.uid) != self.env.uid
                ):
                    raise AccessError(
                        self.env._("You can configure your own subscription only.")
                    )
        return super().create(vals_list)

    def write(self, vals):
        restricted = not self.env.su and not has_any(
            self.env, ("group_management", "group_admin")
        )
        forbidden = any(sub.user_id != self.env.user for sub in self) or set(vals) & {
            "user_id",
            "partner_id",
            "owner_user_id",
            "company_id",
            "last_sent_on",
        }
        if restricted and forbidden:
            raise AccessError(
                self.env._("You can edit only your own report preferences.")
            )
        return super().write(vals)

    def action_send_now(self):
        self.check_access("write")
        return {
            "type": "ir.actions.act_window",
            "res_model": "earlydryer.report.send.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_subscription_id": self.id},
        }

    @api.model
    def _defaults(self):
        users = self.env["res.users"].sudo().search([("share", "=", False)])
        for user in users:
            management = user.has_group("earlydryer_base.group_management")
            branch_manager = user.has_group("earlydryer_base.group_branch_manager")
            for frequency in (
                ["weekly", "monthly"]
                if management
                else ["daily"]
                if branch_manager and len(user.earlydryer_branch_ids) == 1
                else []
            ):
                if self.sudo().search_count(
                    [("user_id", "=", user.id), ("frequency", "=", frequency)]
                ):
                    continue
                self.sudo().create(
                    {
                        "user_id": user.id,
                        "owner_user_id": user.id,
                        "company_id": user.company_id.id,
                        "frequency": frequency,
                        "branch_ids": [(6, 0, user.earlydryer_branch_ids.ids)]
                        if frequency == "daily"
                        else [],
                    }
                )

    def _period(self, today):
        if self.frequency == "weekly":
            end = today - timedelta(days=today.weekday() + 1)
            return end - timedelta(days=6), end
        if self.frequency == "monthly":
            end = today.replace(day=1) - timedelta(days=1)
            return end.replace(day=1), end
        return today, today

    @api.model
    def _cron_due(self):
        now = fields.Datetime.now().replace(tzinfo=ZoneInfo("UTC")).astimezone(LAGOS)
        for sub in self.sudo().search(
            [("active", "=", True), ("frequency", "!=", "daily")]
        ):
            # Catch up a missed Monday/1st after downtime, once for the last complete period.
            if now.hour + now.minute / 60 < sub.send_time:
                continue
            start, end = sub._period(now.date())
            self.env["earlydryer.report.pack"]._schedule(sub, start, end)

    @api.model
    def _generate_reporting_demo(self):
        from ..demo_generator import generate_demo

        return generate_demo(self)
