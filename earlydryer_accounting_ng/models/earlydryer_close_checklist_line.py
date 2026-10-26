# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time

from odoo import api, fields, models
from odoo.fields import Domain


class EarlydryerCloseChecklistLine(models.Model):
    _name = "earlydryer.close.checklist.line"
    _description = "Earlydryer Month-end Checklist Line"
    _order = "sequence, id"

    checklist_id = fields.Many2one(
        "earlydryer.close.checklist", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="checklist_id.company_id", store=True)
    item_id = fields.Many2one("earlydryer.close.checklist.item", ondelete="set null")
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    check_code = fields.Selection(related="item_id.check_code")
    done = fields.Boolean()
    done_by_id = fields.Many2one("res.users", string="Done By", readonly=True)
    done_on = fields.Datetime(readonly=True)
    status = fields.Selection(
        [
            ("todo", "Not Checked"),
            ("ok", "OK"),
            ("issue", "To Fix"),
            ("na", "Not Applicable"),
        ],
        default="todo",
        readonly=True,
    )
    status_message = fields.Char(readonly=True)
    checked_on = fields.Datetime(readonly=True)
    note = fields.Char()

    def write(self, vals):
        self.env["earlydryer.close.checklist"]._earlydryer_check_right()
        if "done" in vals:
            vals = dict(vals)
            if vals["done"]:
                vals.update(done_by_id=self.env.user.id, done_on=fields.Datetime.now())
            else:
                vals.update(done_by_id=False, done_on=False)
        return super().write(vals)

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def action_check(self):
        self.env["earlydryer.close.checklist"]._earlydryer_check_right()
        for line in self:
            method = getattr(line, f"_earlydryer_check_{line.check_code}", None)
            if not method:
                continue
            status, message = method()
            line.sudo().write(
                {
                    "status": status,
                    "status_message": message,
                    "checked_on": fields.Datetime.now(),
                }
            )
        return True

    def _earlydryer_end(self):
        return datetime.combine(self.checklist_id.date_to, time.max)

    def _earlydryer_check_pos_closed(self):
        sessions = (
            self.env["pos.session"]
            .sudo()
            .search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("state", "!=", "closed"),
                    ("start_at", "<=", self._earlydryer_end()),
                ]
            )
        )
        if sessions:
            return "issue", self.env._(
                "%(count)s session(s) still open: %(names)s",
                count=len(sessions),
                names=", ".join(sessions.mapped("name")),
            )
        return "ok", self.env._("Every session of the period is closed.")

    def _earlydryer_check_bank_reconciled(self):
        lines = (
            self.env["account.bank.statement.line"]
            .sudo()
            .search_count(
                [
                    ("company_id", "=", self.company_id.id),
                    ("journal_id.type", "=", "bank"),
                    ("is_reconciled", "=", False),
                    ("date", "<=", self.checklist_id.date_to),
                ]
            )
        )
        if lines:
            return "issue", self.env._(
                "%(count)s bank statement line(s) not reconciled.", count=lines
            )
        return "ok", self.env._("Every imported bank statement line is reconciled.")

    def _earlydryer_clearing_accounts(self):
        company = self.company_id
        accounts = (
            company.earlydryer_gateway_account_id
            | company.earlydryer_cash_transit_account_id
        )
        journals = (
            self.env["account.journal"]
            .sudo()
            .search(
                [
                    ("company_id", "=", company.id),
                    ("earlydryer_role", "in", ("card", "gateway", "rider_cash")),
                ]
            )
        )
        accounts |= journals.default_account_id
        methods = self.env["pos.payment.method"].sudo().search(
            [("company_id", "=", company.id), ("journal_id", "in", journals.ids)]
        )
        accounts |= methods.outstanding_account_id
        return accounts.filtered("reconcile")

    def _earlydryer_unreconciled_clearing_lines(self):
        accounts = self._earlydryer_clearing_accounts()
        if not accounts:
            return self.env["account.move.line"]
        return (
            self.env["account.move.line"]
            .sudo()
            .search(
                [
                    ("account_id", "in", accounts.ids),
                    ("parent_state", "=", "posted"),
                    ("reconciled", "=", False),
                    ("date", "<=", self.checklist_id.date_to),
                    ("company_id", "=", self.company_id.id),
                ]
            )
        )

    def _earlydryer_check_clearing_reconciled(self):
        lines = self._earlydryer_unreconciled_clearing_lines()
        if lines:
            return "issue", self.env._(
                "%(count)s unreconciled line(s) on %(accounts)s.",
                count=len(lines),
                accounts=", ".join(lines.account_id.mapped("display_name")),
            )
        return "ok", self.env._("Card, gateway, rider and in-transit clearing are clear.")

    def _earlydryer_check_wallet_control(self):
        control = (
            self.env["earlydryer.wallet.control"]
            .sudo()
            .create(
                {"date": self.checklist_id.date_to, "company_id": self.company_id.id}
            )
        )
        currency = self.company_id.currency_id
        if not currency.is_zero(control.unexplained):
            return "issue", self.env._(
                "Unexplained wallet difference: %(amount)s.",
                amount=currency.format(control.unexplained),
            )
        if not currency.is_zero(control.difference):
            return "ok", self.env._(
                "Difference %(amount)s, explained by till transactions not "
                "accounted yet.",
                amount=currency.format(control.difference),
            )
        return "ok", self.env._("Wallet balances agree with the advances account.")

    def _earlydryer_check_analytic_gaps(self):
        count = (
            self.env["account.move.line"]
            .sudo()
            .search_count(
                [
                    ("earlydryer_analytic_gap", "=", True),
                    ("company_id", "=", self.company_id.id),
                    ("date", ">=", self.checklist_id.date_from),
                    ("date", "<=", self.checklist_id.date_to),
                ]
            )
        )
        if count:
            return "issue", self.env._(
                "%(count)s income or expense line(s) without a plant.", count=count
            )
        return "ok", self.env._("Every income and expense line has a plant.")

    def _earlydryer_check_wht_prepared(self):
        lines = (
            self.env["account.move.line"]
            .sudo()
            .search(
                [
                    ("tax_line_id.earlydryer_wht_category_id", "!=", False),
                    ("parent_state", "=", "posted"),
                    ("reconciled", "=", False),
                    ("company_id", "=", self.company_id.id),
                    ("date", "<=", self.checklist_id.date_to),
                ]
            )
        )
        if lines:
            amount = -sum(lines.mapped("balance"))
            return "issue", self.env._(
                "WHT of %(amount)s withheld and not remitted yet.",
                amount=self.company_id.currency_id.format(amount),
            )
        return "ok", self.env._("No WHT awaiting remittance.")

    def _earlydryer_check_depreciation(self):
        if "account.asset.line" not in self.env:
            return "na", self.env._("Asset management is not installed.")
        domain = Domain(
            [
                ("type", "=", "depreciate"),
                ("init_entry", "=", False),
                ("move_check", "=", False),
                ("line_date", "<=", self.checklist_id.date_to),
                ("asset_id.state", "=", "open"),
                ("asset_id.company_id", "=", self.company_id.id),
            ]
        )
        count = self.env["account.asset.line"].sudo().search_count(domain)
        if count:
            return "issue", self.env._(
                "%(count)s depreciation line(s) not posted.", count=count
            )
        return "ok", self.env._("Depreciation is posted up to the period end.")

    def _earlydryer_check_vat_return(self):
        if not self.company_id.earlydryer_vat_registered:
            return "na", self.env._("Earlydryer is not VAT-registered.")
        if (self.company_id.tax_lock_date or fields.Date.to_date("1900-01-01")) >= (
            self.checklist_id.date_to
        ):
            return "ok", self.env._("Tax lock date covers the period.")
        return "issue", self.env._(
            "Prepare the VAT return, then set the tax lock date."
        )

    def _earlydryer_check_lock_date(self):
        company = self.company_id
        lock = max(
            date
            for date in (
                company.fiscalyear_lock_date,
                company.sale_lock_date,
                company.purchase_lock_date,
                fields.Date.to_date("1900-01-01"),
            )
            if date
        )
        if lock >= self.checklist_id.date_to:
            return "ok", self.env._("Locked up to %(date)s.", date=lock)
        return "issue", self.env._("Set the lock date to %(date)s.", date=self.checklist_id.date_to)

    def action_open_tool(self):
        """Open what the step is about (lock date wizard, gaps, reports...)."""
        self.ensure_one()
        code = self.check_code
        xmlids = {
            "lock_date": "account_lock_date_update.account_update_lock_date_act_window",
            "analytic_gaps": "earlydryer_accounting_ng.action_earlydryer_analytic_gaps",
            "wht_prepared": "earlydryer_accounting_ng.earlydryer_wht_report_wizard_action",
            "pos_closed": "point_of_sale.action_pos_session",
            "depreciation": "account_asset_management.account_asset_action",
            "wallet_control": "earlydryer_wallet.earlydryer_wallet_control_server_action",
        }
        xmlid = xmlids.get(code)
        if code == "clearing_reconciled":
            lines = self._earlydryer_unreconciled_clearing_lines()
            return {
                "type": "ir.actions.act_window",
                "name": self.env._("Unreconciled Clearing Lines"),
                "res_model": "account.move.line",
                "view_mode": "list,form",
                "domain": [("id", "in", lines.ids)],
            }
        if not xmlid or not self.env.ref(xmlid, raise_if_not_found=False):
            return False
        action = self.env["ir.actions.actions"]._for_xml_id(xmlid)
        if code == "lock_date":
            action["context"] = {"default_company_id": self.company_id.id}
        return action

    @api.model
    def _earlydryer_lock_action(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "account_lock_date_update.account_update_lock_date_act_window"
        )
