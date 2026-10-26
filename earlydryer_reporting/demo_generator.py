# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

"""Deterministic, relative-date demo generator; never invoked in normal data."""

from datetime import datetime, timedelta
from random import Random

from odoo import Command, fields


def generate_demo(self):
    if not self.env.su or not self.env.context.get("install_demo"):
        from odoo.exceptions import AccessError

        raise AccessError(
            self.env._("Demo generation is available during installation only.")
        )
    rng = Random(9791)
    branches = self.env.ref("earlydryer_base.branch_plant_1") | self.env.ref(
        "earlydryer_base.branch_plant_2"
    )
    products = self.env["product.product"].search(
        [("earlydryer_kind", "=", "laundry"), ("sale_ok", "=", True)], limit=8
    )
    if not products:
        return
    anchor = fields.Date.context_today(self.with_context(tz="Africa/Lagos"))
    partners = self.env["res.partner"].create(
        [
            {"name": f"Report demo customer {n:02d}", "phone": f"+23480320{n:05d}"}
            for n in range(20)
        ]
    )
    employees = {
        branch.id: self.env["hr.employee"].create(
            {
                "name": "Report demo " + branch.name,
                "earlydryer_branch_id": branch.id,
            }
        )
        for branch in branches
    }
    for branch in branches:
        for channel in ("walk_in", "pickup", "corporate"):
            domain = [
                ("earlydryer_branch_id", "=", branch.id),
                ("earlydryer_channel", "=", channel),
            ]
            if not self.env["product.pricelist"].search_count(domain):
                self.env["product.pricelist"].create(
                    {
                        "name": f"Report demo {branch.code} {channel}",
                        "currency_id": branch.company_id.currency_id.id,
                        "company_id": branch.company_id.id,
                        "earlydryer_branch_id": branch.id,
                        "earlydryer_channel": channel,
                    }
                )
    sources = []
    metadata = []
    for offset in range(60):
        for branch in branches:
            for index in range(2):
                product = products[(offset + index) % len(products)]
                stamp = datetime.combine(
                    anchor - timedelta(days=offset), datetime.min.time()
                ) + timedelta(hours=8 + index)
                sources.append(
                    {
                        "partner_id": partners[(offset + index) % 20].id,
                        "earlydryer_branch_id": branch.id,
                        "earlydryer_channel": [
                            "walk_in",
                            "pickup",
                            "whatsapp",
                            "corporate",
                        ][rng.randrange(4)],
                        "earlydryer_express": index == 1 and offset % 3 == 0,
                        "order_line": [
                            Command.create(
                                {
                                    "product_id": product.id,
                                    "product_uom_qty": rng.randint(1, 4),
                                    "price_unit": 1200 + offset % 5 * 200,
                                    "discount": 0,
                                    "tax_ids": [Command.clear()],
                                }
                            )
                        ],
                    }
                )
                metadata.append((stamp, branch, offset, index))
    sales = self.env["sale.order"].create(sources)
    sales.action_confirm()
    for sale, (stamp, branch, offset, index) in zip(sales, metadata):
        sale.write({"date_order": stamp})
        for job in sale.laundry_job_ids:
            hours = 8 if job.express else 30 + offset % 24
            ready = stamp + timedelta(hours=hours)
            state = (
                "received"
                if offset == 0
                else "washed"
                if offset == 1
                else "ready"
                if offset < 5
                else "delivered"
                if index
                else "collected"
            )
            values = {
                "received_on": stamp,
                "promised_on": stamp + timedelta(hours=24 if offset % 5 else 72),
                "ready_on": ready if state not in ("received", "washed") else False,
                "closed_on": ready + timedelta(hours=6)
                if state in ("collected", "delivered")
                else False,
                "state": state,
            }
            job.with_context(earlydryer_stage_move=True).write(values)
            job.stage_log_ids.filtered(lambda log: log.to_state == "received").write(
                {"date": stamp}
            )
            previous = "received"
            states = (
                ["tagged", "sorted", "washed"]
                if state == "washed"
                else []
                if state == "received"
                else [
                    "tagged",
                    "sorted",
                    "washed",
                    "dried",
                    "ironed",
                    "qc",
                    "packed",
                    "ready",
                ]
                + ([state] if state in ("collected", "delivered") else [])
            )
            for number, target in enumerate(states, 1):
                self.env["laundry.job.stage.log"].create(
                    {
                        "job_id": job.id,
                        "from_state": previous,
                        "to_state": target,
                        "date": stamp
                        + timedelta(hours=hours * number / max(1, len(states))),
                        "employee_id": employees[branch.id].id if offset % 9 else False,
                    }
                )
                previous = target
            if offset % 13 == 0 and job.item_ids:
                item = job.item_ids[:1]
                item.write(
                    {
                        "qc_state": "rework",
                        "qc_date": ready - timedelta(hours=2),
                        "rework_count": 1,
                    }
                )
                item.write({"qc_state": "passed", "qc_date": ready})
            if offset % 19 == 0 and job.item_ids:
                item = job.item_ids[:1]
                item.write(
                    {
                        "missing": True,
                        "earlydryer_missing_on": stamp + timedelta(hours=2),
                    }
                )
    # Genuine vendor bills, posted with plant analytic allocation.
    company = self.env.company
    expense = self.env["account.account"].search(
        [("account_type", "=", "expense"), ("company_ids", "in", company.ids)], limit=1
    )
    direct = (
        self.env["account.account"].search(
            [
                ("account_type", "=", "expense_direct_cost"),
                ("company_ids", "in", company.ids),
            ],
            limit=1,
        )
        or expense
    )
    journal = self.env["account.journal"].search(
        [("company_id", "=", company.id), ("type", "=", "purchase")], limit=1
    )
    vendor = self.env["res.partner"].create(
        {"name": "Report demo supplies", "supplier_rank": 1}
    )
    if expense and journal:
        for branch in branches:
            for offset in (3, 17, 35, 50):
                account = direct if offset in (17, 50) else expense
                bill = self.env["account.move"].create(
                    {
                        "move_type": "in_invoice",
                        "partner_id": vendor.id,
                        "journal_id": journal.id,
                        "invoice_date": anchor - timedelta(days=offset),
                        "date": anchor - timedelta(days=offset),
                        "earlydryer_branch_id": branch.id,
                        "invoice_line_ids": [
                            Command.create(
                                {
                                    "name": "Demo plant supplies",
                                    "account_id": account.id,
                                    "quantity": 1,
                                    "price_unit": 7500,
                                    "tax_ids": [Command.clear()],
                                    "analytic_distribution": {
                                        str(branch.analytic_account_id.id): 100
                                    },
                                }
                            )
                        ],
                    }
                )
                bill.action_post()
    # Cash-backed wallet advances; default_date is consumed by the transaction's create defaults.
    for branch in branches:
        if branch.cash_journal_id:
            for offset in (4, 20, 45):
                stamp = datetime.combine(
                    anchor - timedelta(days=offset), datetime.min.time()
                ) + timedelta(hours=10)
                self.env["earlydryer.wallet.topup.wizard"].with_context(
                    default_date=stamp
                ).create(
                    {
                        "partner_id": partners[offset % 20].id,
                        "earlydryer_branch_id": branch.id,
                        "journal_id": branch.cash_journal_id.id,
                        "amount": 5000,
                    }
                ).action_confirm()
    # A posted POS session per plant, with cash and retail lines.
    retail = self.env["product.product"].search(
        [("earlydryer_kind", "=", "retail")], limit=1
    )
    for branch in branches:
        config = branch.pos_config_ids[:1]
        if not config or not retail:
            continue
        cash = config.payment_method_ids.filtered("is_cash_count")[:1]
        if not cash:
            continue
        session = config.current_session_id or self.env["pos.session"].create(
            {"config_id": config.id, "user_id": self.env.uid}
        )
        if session.state == "opening_control":
            session.action_pos_session_open()
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "partner_id": partners[0].id,
                "amount_tax": 0,
                "amount_total": 1900,
                "amount_paid": 1900,
                "amount_return": 0,
                "lines": [
                    Command.create(
                        {
                            "product_id": retail.id,
                            "qty": 2,
                            "price_unit": 1000,
                            "discount": 5,
                            "price_subtotal": 1900,
                            "price_subtotal_incl": 1900,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
                "payment_ids": [
                    Command.create({"payment_method_id": cash.id, "amount": 1900})
                ],
            }
        )
        order.action_pos_order_paid()
        session.cash_register_balance_end_real = session.cash_register_balance_end
        session._validate_session()
        if (
            session.state != "closed"
            or not session.move_id
            or session.move_id.state != "posted"
        ):
            raise ValueError("Demo POS session was not posted")
    self._defaults()
