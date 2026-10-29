# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models
from odoo.fields import Command

_logger = logging.getLogger(__name__)


class EarlydryerAccountingDemo(models.AbstractModel):
    """Demo data built in code: the accounts and journals only exist once the
    setup wizard ran on the demo company."""

    _name = "earlydryer.accounting.demo"
    _description = "Earlydryer Accounting Demo Data"

    @api.model
    def _earlydryer_load_demo(self):
        ref = self.env.ref
        env = self.with_user(ref("base.user_admin")).env
        company = env.company
        if not company.chart_template:
            return False
        wizard = env["earlydryer.accounting.setup.wizard"].create(
            {
                "bank_name": "Example Bank (fictional)",
                "bank_acc_number": "0000000001",
                "card_providers": "Demo Terminals",
            }
        )
        wizard._earlydryer_run()
        plant_1 = ref("earlydryer_base.branch_plant_1")
        plant_2 = ref("earlydryer_base.branch_plant_2")
        plant_1.earlydryer_cash_float = 20000
        plant_2.earlydryer_cash_float = 15000
        self._earlydryer_demo_bills(env)
        self._earlydryer_demo_corporate_invoice(env)
        bank = env["account.journal"].search(
            [("company_id", "=", company.id), ("earlydryer_role", "=", "bank")], limit=1
        )
        for config_xmlid, employee_xmlid in (
            (
                "earlydryer_service_catalog.pos_config_counter_p1",
                "earlydryer_laundry_order.employee_front_desk_p1",
            ),
            (
                "earlydryer_pos.pos_config_counter_p2",
                "earlydryer_pos.employee_front_desk_p2",
            ),
        ):
            config = ref(config_xmlid).with_env(env)
            try:
                with env.cr.savepoint():
                    self._earlydryer_demo_pos_day(config, ref(employee_xmlid))
            except Exception:  # pylint: disable=broad-except  # demo only
                _logger.exception("Demo POS day failed for %s.", config.name)
                continue
            branch = config.earlydryer_branch_id
            lodgement = env["earlydryer.cash.lodgement.wizard"].create(
                {
                    "branch_id": branch.id,
                    "bank_journal_id": bank.id,
                    "reference": f"DEMO-SLIP-{branch.code}",
                }
            )
            if lodgement.amount > 0:
                lodgement._earlydryer_lodge()
        rider = env["hr.employee"].search(
            [("name", "=", "Demo Rider (accounting)")], limit=1
        )
        if not rider:
            rider = env["hr.employee"].create({"name": "Demo Rider (accounting)"})
        env["account.move"]._earlydryer_rider_handover(
            plant_1, 5000.0, rider, ref="DEMO"
        )
        return True

    @api.model
    def _earlydryer_demo_bills(self, env):
        Partner = env["res.partner"]
        categories = (
            (
                "Demo Consulting Ltd",
                True,
                "earlydryer_accounting_ng.wht_category_professional",
                "12345678-0001",
                150000.0,
                "Bookkeeping support",
            ),
            (
                "Musa Demo (landlord)",
                False,
                "earlydryer_accounting_ng.wht_category_rent",
                "23456789-0001",
                400000.0,
                "Plant 2 rent, one month",
            ),
        )
        for name, is_company, category, tin, amount, label in categories:
            vendor = Partner.search([("name", "=", name)], limit=1) or Partner.create(
                {
                    "name": name,
                    "is_company": is_company,
                    "vat": tin,
                    "country_id": env.ref("base.ng").id,
                    "earlydryer_wht_category_id": env.ref(category).id,
                    "earlydryer_wht_vendor_type": "company"
                    if is_company
                    else "individual",
                }
            )
            bill = env["account.move"].create(
                {
                    "move_type": "in_invoice",
                    "partner_id": vendor.id,
                    "invoice_date": fields.Date.context_today(self),
                    "ref": f"DEMO-{vendor.id}",
                    "earlydryer_branch_id": env.ref(
                        "earlydryer_base.branch_plant_2"
                    ).id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": label,
                                "quantity": 1,
                                "price_unit": amount,
                                "account_id": env.company.expense_account_id.id,
                            }
                        )
                    ],
                }
            )
            bill.action_post()

    @api.model
    def _earlydryer_demo_corporate_invoice(self, env):
        customer = env["res.partner"].create(
            {
                "name": "Demo Corporate Client Ltd",
                "is_company": True,
                "vat": "34567890-0001",
                "country_id": env.ref("base.ng").id,
            }
        )
        product = env["product.product"].search(
            [("earlydryer_kind", "=", "laundry"), ("sale_ok", "=", True)], limit=1
        )
        invoice = env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": customer.id,
                "invoice_date": fields.Date.context_today(self),
                "earlydryer_branch_id": env.ref("earlydryer_base.branch_plant_1").id,
                "invoice_line_ids": [
                    Command.create(
                        {"product_id": product.id, "quantity": 20, "price_unit": 2500.0}
                    )
                ],
            }
        )
        invoice.action_post()
        deduction = env["earlydryer.wht.deduction.wizard"].create(
            {
                "invoice_id": invoice.id,
                "amount": round(invoice.amount_untaxed * 0.10, 2),
                "reference": "DEMO-WHT-CN-001",
            }
        )
        deduction.action_register()

    @api.model
    def _earlydryer_demo_pos_day(self, config, employee):
        """One day at the till: laundry with a surcharge, express and retail,
        paid in cash and by card; the session is closed."""
        env = config.env
        if not config.current_session_id:
            config.open_ui()
        session = config.current_session_id
        session.set_opening_control(0, None)
        Catalog = env["earlydryer.catalog"]
        ref = env.ref
        shirt = Catalog.get_laundry_product(
            ref("earlydryer_service_catalog.garment_category_shirt"),
            ref("earlydryer_service_catalog.service_type_wash_iron"),
        )
        suit = Catalog.get_laundry_product(
            ref("earlydryer_service_catalog.garment_category_suit"),
            ref("earlydryer_service_catalog.service_type_dry_cleaning"),
        )
        beads = ref("earlydryer_service_catalog.surcharge_beads")
        retail = env["product.product"].search(
            [("earlydryer_kind", "=", "retail"), ("available_in_pos", "=", True)],
            limit=1,
        )
        price = config.pricelist_id._get_product_price
        cash = config.payment_method_ids.filtered("is_cash_count")[:1]
        card = config.payment_method_ids.filtered(
            lambda method: method.journal_id.earlydryer_role == "card"
        )[:1]
        partner = ref("earlydryer_laundry_order.partner_customer_adaeze")
        orders = [
            [(shirt, 4, None), (suit, 1, beads)],
            [(retail, 2, None)] if retail else [(shirt, 2, None)],
        ]
        payloads = []
        for number, garments in enumerate(orders, start=1):
            lines = []
            for product, qty, surcharge in garments:
                uuid = f"ed-acc-demo-{config.id}-{number}-{product.id}"
                lines.append(
                    config._earlydryer_ui_line(
                        product, qty, price(product, qty) or 1000.0, uuid
                    )
                )
                if surcharge:
                    lines.append(
                        config._earlydryer_ui_line(
                            surcharge.product_id,
                            qty,
                            price(surcharge.product_id, qty) or 500.0,
                            f"{uuid}-s",
                            earlydryer_parent_line_uuid=uuid,
                            earlydryer_surcharge_id=surcharge.id,
                        )
                    )
            total = sum(line[2]["price_subtotal_incl"] for line in lines)
            method = card if number == 2 and card else cash
            payloads.append(
                {
                    "uuid": f"ed-acc-demo-order-{config.id}-{number}",
                    "name": f"Accounting demo {number}",
                    "session_id": session.id,
                    "partner_id": partner.id,
                    "employee_id": employee.id,
                    "pricelist_id": config.pricelist_id.id,
                    "user_id": env.uid,
                    "lines": lines,
                    "payment_ids": [
                        (0, 0, {"amount": total, "payment_method_id": method.id})
                    ],
                    "amount_paid": total,
                    "amount_total": total,
                    "amount_tax": 0.0,
                    "amount_return": 0.0,
                    "date_order": fields.Datetime.to_string(fields.Datetime.now()),
                    "state": "paid",
                    "to_invoice": False,
                    "last_order_preparation_change": "{}",
                }
            )
        env["pos.order"].sync_from_ui(payloads)
        cash_total = sum(
            session.order_ids.payment_ids.filtered(
                lambda payment: payment.payment_method_id.is_cash_count
            ).mapped("amount")
        )
        session.post_closing_cash_details(cash_total)
        session.close_session_from_ui()
        return session
