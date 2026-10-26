# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models
from odoo.exceptions import AccessError


class EarlydryerBranch(models.Model):
    _inherit = "earlydryer.branch"

    currency_id = fields.Many2one(related="company_id.currency_id")
    earlydryer_cash_float = fields.Monetary(
        string="Cash Float",
        currency_field="currency_id",
        tracking=True,
        help="Approved float left in the till after the lodgement. Lodging more "
        "(leaving less than the float) needs a Branch Manager. PLACEHOLDER until "
        "Earlydryer sets the float per plant.",
    )
    earlydryer_rider_journal_id = fields.Many2one(
        "account.journal",
        string="Rider Cash Journal",
        check_company=True,
        domain=[("type", "=", "cash")],
        help="Cash collected by riders on delivery, before handover at the plant.",
    )
    earlydryer_cash_account_id = fields.Many2one(
        related="cash_journal_id.default_account_id", string="Plant Cash Account"
    )
    earlydryer_rider_account_id = fields.Many2one(
        related="earlydryer_rider_journal_id.default_account_id",
        string="Rider Cash Account",
    )

    # ------------------------------------------------------------------
    # Rights (enforced in Python: the wizards run their entries with sudo)
    # ------------------------------------------------------------------

    def _earlydryer_check_cash_right(self, right):
        """Raise unless the user may do ``right`` on these plants.

        ``lodge`` / ``handover``: Finance on every plant, Branch Manager on
        their own plants. ``below_float``: Branch Manager (own plants) or
        Management. ``report``: anyone working on the plant.
        """
        user = self.env.user
        if self.env.su or user.has_group("earlydryer_base.group_admin"):
            return True
        allowed = user._earlydryer_allowed_branches()
        own = all(branch in allowed for branch in self)
        if right == "report":
            ok = own
        elif right in ("lodge", "handover"):
            ok = user.has_group("earlydryer_base.group_finance") or (
                own and user.has_group("earlydryer_base.group_branch_manager")
            )
        elif right == "below_float":
            ok = user.has_group("earlydryer_base.group_management") or (
                own and user.has_group("earlydryer_base.group_branch_manager")
            )
        else:
            ok = False
        if not ok:
            messages = {
                "lodge": self.env._("You may not lodge the cash of %(branches)s."),
                "handover": self.env._(
                    "You may not record rider handovers for %(branches)s."
                ),
                "below_float": self.env._(
                    "Leaving less than the float in the till of %(branches)s needs "
                    "a Branch Manager of the plant or Management."
                ),
                "report": self.env._(
                    "You may not read the cash report of %(branches)s."
                ),
            }
            raise AccessError(
                messages.get(right, messages["report"])
                % {"branches": ", ".join(self.sudo().mapped("display_name"))}
            )
        return True

    def _earlydryer_cash_balance(self, date):
        """Posted balance of the plant cash account at the end of ``date``."""
        self.ensure_one()
        account = self.sudo().earlydryer_cash_account_id
        if not account:
            return 0.0
        groups = (
            self.env["account.move.line"]
            .sudo()
            ._read_group(
                [
                    ("account_id", "=", account.id),
                    ("parent_state", "=", "posted"),
                    ("date", "<=", date),
                    ("company_id", "=", self.company_id.id),
                ],
                [],
                ["balance:sum"],
            )
        )
        return groups[0][0] or 0.0

    def action_earlydryer_lodgement(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_accounting_ng.earlydryer_cash_lodgement_wizard_action"
        )
        action["context"] = {"default_branch_id": self.id}
        return action

    def action_earlydryer_daily_cash_report(self, date=None):
        """PDF of the daily cash report of these plants (the notifications
        module emails it)."""
        self._earlydryer_check_cash_right("report")
        date = date or fields.Date.context_today(self)
        return self.env.ref(
            "earlydryer_accounting_ng.action_report_daily_cash"
        ).report_action(self, data={"date": fields.Date.to_string(date)})
