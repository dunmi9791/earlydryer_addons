# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..tools import LAGOS

EOD_FIELDS = {
    "eod_report_time",
    "eod_email_recipient_ids",
    "eod_whatsapp_recipient_ids",
}


class EarlydryerBranch(models.Model):
    _inherit = "earlydryer.branch"
    eod_report_time = fields.Float(
        default=20, groups="earlydryer_base.group_branch_manager"
    )
    eod_email_recipient_ids = fields.Many2many(
        "res.partner",
        "notify_eod_email_partner_rel",
        groups="earlydryer_base.group_branch_manager",
    )
    eod_whatsapp_recipient_ids = fields.Many2many(
        "res.partner",
        "notify_eod_wa_partner_rel",
        groups="earlydryer_base.group_branch_manager",
    )
    eod_last_sent_on = fields.Date(
        readonly=True, copy=False, groups="earlydryer_base.group_branch_manager"
    )

    @api.constrains("eod_report_time")
    def _check_eod_time(self):
        if any(not 0 <= b.eod_report_time < 24 for b in self):
            raise ValidationError(
                self.env._("EOD time must be between 00:00 and 23:59.")
            )

    def write(self, vals):
        if vals and set(vals) <= EOD_FIELDS and not self.env.su:
            self.check_access("read")
            if not self.env.user.has_group("earlydryer_base.group_branch_manager"):
                raise AccessError(
                    self.env._("Only managers can configure EOD reports.")
                )
            return super(EarlydryerBranch, self.sudo()).write(vals)
        return super().write(vals)

    def action_eod_report(self):
        self.check_access("read")
        if not self.env.user.has_group("earlydryer_base.group_branch_manager"):
            raise AccessError(self.env._("Only managers can send EOD reports."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "earlydryer.notify.eod.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_branch_id": self.id},
        }

    def _earlydryer_eod_figures(self, date):
        self.ensure_one()
        self.check_access("read")
        day = fields.Date.to_date(date)
        start = (
            datetime.combine(day, time.min, tzinfo=LAGOS)
            .astimezone(ZoneInfo("UTC"))
            .replace(tzinfo=None)
        )
        end = start + timedelta(days=1)
        jobs = self.env["laundry.job"].search([("earlydryer_branch_id", "=", self.id)])
        received = jobs.filtered(
            lambda j: start <= j.received_on < end and j.state != "cancelled"
        )
        completed = jobs.filtered(
            lambda j: (
                j.closed_on
                and start <= j.closed_on < end
                and j.state in ("collected", "delivered")
            )
        )
        orders = self.env["pos.order"].search(
            [
                ("config_id.earlydryer_branch_id", "=", self.id),
                ("date_order", ">=", start),
                ("date_order", "<", end),
                ("state", "in", ["paid", "done", "invoiced"]),
            ]
        )
        payments = {}
        for payment in orders.payment_ids:
            key = payment.payment_method_id.name
            payments[key] = payments.get(key, 0) + payment.amount
        backend_payments = self.env["account.payment"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("date", "=", day),
                ("payment_type", "=", "inbound"),
                ("move_id.state", "=", "posted"),
                ("state", "in", ["in_process", "paid"]),
            ]
        )
        backend_payments = backend_payments.filtered(
            lambda payment: (
                self.env["earlydryer.notify.message"]._branch(payment) == self
            )
        )
        for payment in backend_payments:
            key = payment.journal_id.name
            payments[key] = payments.get(key, 0) + payment.amount
        topups = self.env["earlydryer.wallet.transaction"].search(
            [
                ("earlydryer_branch_id", "=", self.id),
                ("state", "=", "posted"),
                ("type", "=", "topup"),
                ("date", ">=", start),
                ("date", "<", end),
            ]
        )
        scans = self.env["earlydryer.scan.log"].search_count(
            [
                ("earlydryer_branch_id", "=", self.id),
                ("is_mismatch", "=", True),
                ("date", ">=", start),
                ("date", "<", end),
            ]
        )
        return {
            "orders": len(received),
            "sales_value": sum(received.mapped("amount_total")),
            "collected": len(completed.filtered(lambda j: j.state == "collected")),
            "delivered": len(completed.filtered(lambda j: j.state == "delivered")),
            "ready": len(jobs.filtered(lambda j: j.state == "ready")),
            "overdue": len(jobs.filtered("is_overdue")),
            "payments": payments,
            "cash": sum(
                payment.amount
                for payment in backend_payments
                if payment.journal_id.type == "cash"
            )
            + sum(
                p.amount
                for p in orders.payment_ids
                if p.payment_method_id.is_cash_count
            ),
            "discounts": sum(
                line.qty * line.price_unit * line.discount / 100
                for line in orders.lines
            ),
            "unpaid_releases": len(completed.filtered("earlydryer_released_unpaid")),
            "wallet_topups": sum(topups.mapped("amount")),
            "scan_mismatches": scans,
        }

    @api.model
    def _cron_eod(self):
        local = fields.Datetime.now().replace(tzinfo=ZoneInfo("UTC")).astimezone(LAGOS)
        for branch in self.search([("active", "=", True)]):
            if local.hour + local.minute / 60 >= branch.eod_report_time:
                self.env["earlydryer.notify.eod.report"]._schedule(branch, local.date())
