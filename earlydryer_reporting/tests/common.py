# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import datetime, timedelta

from odoo import Command, fields
from odoo.addons.earlydryer_wallet.tests.common import WalletCommon
from odoo.addons.queue_job.tests.common import trap_jobs


class ReportingCommon(WalletCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Kpi = cls.env["earlydryer.kpi"]
        cls.start = fields.Date.to_date("2026-10-01")
        cls.end = fields.Date.to_date("2026-10-10")
        cls.stamp = datetime(2026, 10, 5, 9)
        plan = cls.env.ref("earlydryer_accounting_ng.analytic_plan_plants")
        for branch in cls.branch_1 | cls.branch_2:
            branch.analytic_account_id = cls.env["account.analytic.account"].create(
                {
                    "name": branch.name,
                    "plan_id": plan.id,
                    "company_id": cls.env.company.id,
                }
            )
        cls.hr_user = cls._new_user("report_hr", "earlydryer_base.group_hr")
        cls.env["earlydryer.notify.provider"].create(
            {
                "name": "Reporting test",
                "channel": "whatsapp",
                "provider_type": "log_only",
            }
        )
        cls.expense_account = cls.env["account.account"].create(
            {
                "name": "Reporting direct cost",
                "code": "ER6001",
                "account_type": "expense_direct_cost",
                "company_ids": [Command.set(cls.env.company.ids)],
            }
        )
        cls.income_account = cls.env["account.account"].create(
            {
                "name": "Reporting income",
                "code": "ER7001",
                "account_type": "income",
                "company_ids": [Command.set(cls.env.company.ids)],
            }
        )
        cls.general = cls.env["account.journal"].search(
            [("company_id", "=", cls.env.company.id), ("type", "=", "general")], limit=1
        )

    def setUp(self):
        super().setUp()
        self.trap = self.enterContext(trap_jobs())

    def job(
        self,
        amount=100,
        branch=None,
        partner=None,
        received=None,
        hours=None,
        promised=20,
        state=None,
    ):
        branch = branch or self.branch_1
        result = self._create_job(branch=branch, partner=partner or self.partner)
        result.sale_order_id.order_line.write(
            {"price_unit": amount, "tax_ids": [Command.clear()]}
        )
        stamp = received or self.stamp
        result.sale_order_id.date_order = stamp
        vals = {"received_on": stamp, "promised_on": stamp + timedelta(hours=promised)}
        if hours is not None:
            vals["ready_on"] = stamp + timedelta(hours=hours)
            vals["state"] = "ready"
        if state:
            vals["state"] = state
            if state in ("collected", "delivered"):
                vals["closed_on"] = stamp + timedelta(hours=hours or 24)
        result.with_context(earlydryer_stage_move=True).write(vals)
        result.invalidate_recordset(["amount_total", "amount_due", "amount_paid"])
        return result

    def compute(
        self,
        codes=None,
        branches=None,
        start=None,
        end=None,
        user=None,
        compare="previous",
    ):
        return self.Kpi.with_user(user or self.env.user).compute(
            codes or [],
            (branches or self.branch_1).ids,
            start or self.start,
            end or self.end,
            compare,
        )

    def entry(self, amount, account=None, branch=None, distribution=None, day=None):
        branch = branch or self.branch_1
        account = account or self.expense_account
        income = account.account_type in ("income", "income_other")
        cash = self.journal_cash.default_account_id
        move = self.env["account.move"].create(
            {
                "date": day or self.start,
                "journal_id": self.general.id,
                "earlydryer_branch_id": branch.id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "Reporting fixture",
                            "account_id": account.id,
                            "debit": 0 if income else amount,
                            "credit": amount if income else 0,
                            "analytic_distribution": distribution
                            or {str(branch.analytic_account_id.id): 100},
                        }
                    ),
                    Command.create(
                        {
                            "name": "Counterpart",
                            "account_id": cash.id,
                            "debit": amount if income else 0,
                            "credit": 0 if income else amount,
                        }
                    ),
                ],
            }
        )
        move.action_post()
        return move
