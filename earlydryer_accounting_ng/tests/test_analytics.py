# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.fields import Command
from odoo.tests import tagged

from .common import AccountingCommon


@tagged("post_install", "-at_install")
class TestAnalytics(AccountingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.line_wash = ref("earlydryer_accounting_ng.service_line_wash_iron")
        cls.line_dry = ref("earlydryer_accounting_ng.service_line_dry_cleaning")
        cls.line_retail = ref("earlydryer_accounting_ng.service_line_retail")
        cls.svc_wi.earlydryer_service_line_id = cls.line_wash
        cls.svc_dc.earlydryer_service_line_id = cls.line_dry
        cls.retail = cls.env["product.product"].create(
            {
                "name": "T Detergent",
                "earlydryer_kind": "retail",
                "type": "consu",
                "list_price": 1500.0,
                "available_in_pos": True,
                "invoice_policy": "order",
                "taxes_id": [Command.clear()],
            }
        )
        cls.plant_1 = cls.branch_1.analytic_account_id

    def _keys(self, line):
        return {
            int(account_id)
            for key in (line.analytic_distribution or {})
            for account_id in key.split(",")
        }

    def test_invoice_from_sale_order(self):
        self.assertEqual(self.retail.earlydryer_service_line_id, self.line_retail)
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "earlydryer_branch_id": self.branch_1.id,
                "order_line": [
                    Command.create({"product_id": self.retail.id, "product_uom_qty": 2})
                ],
            }
        )
        self.assertEqual(
            self._keys(order.order_line), {self.plant_1.id, self.line_retail.id}
        )
        order.action_confirm()
        invoice = order._create_invoices()
        self.assertEqual(invoice.earlydryer_branch_id, self.branch_1)
        line = invoice.invoice_line_ids
        self.assertEqual(self._keys(line), {self.plant_1.id, self.line_retail.id})
        self.assertEqual(
            line.account_id, self.company.earlydryer_retail_income_account_id
        )
        invoice.action_post()
        self.assertFalse(line.earlydryer_analytic_gap)

    def test_pos_session_split_by_service_line(self):
        parent_uuid = "t-acc-garment"
        lines = [
            self._line(self.shirt_wi, qty=2, price=1000.0),
            self._line(self.shirt_dc, qty=1, price=3000.0, uuid=parent_uuid),
            self._line(
                self.sur_beads.product_id,
                qty=1,
                price=500.0,
                earlydryer_parent_line_uuid=parent_uuid,
                earlydryer_surcharge_id=self.sur_beads.id,
            ),
            self._line(self.retail, qty=1, price=1500.0),
        ]
        order = self._sync(self._payload(lines))
        session = order.session_id
        self._close_session(session)
        self.assertEqual(session.move_id.earlydryer_branch_id, self.branch_1)
        revenue = session.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type == "income"
        )
        by_line = {}
        for line in revenue:
            keys = self._keys(line)
            self.assertIn(self.plant_1.id, keys, line.name)
            service = keys - {self.plant_1.id}
            self.assertEqual(len(service), 1, line.name)
            key = service.pop()
            by_line[key] = by_line.get(key, 0.0) + line.balance
        self.assertAlmostEqual(by_line[self.line_wash.id], -2000.0)
        # the surcharge goes with its garment line: dry cleaning
        self.assertAlmostEqual(by_line[self.line_dry.id], -3500.0)
        self.assertAlmostEqual(by_line[self.line_retail.id], -1500.0)
        laundry = revenue.filtered(
            lambda l: (
                self.line_wash.id in self._keys(l) or self.line_dry.id in self._keys(l)
            )
        )
        self.assertEqual(
            laundry.account_id, self.company.earlydryer_laundry_income_account_id
        )
        for line in session.move_id.line_ids.filtered(lambda l: l.account_id.reconcile):
            self.assertIn(self.plant_1.id, self._keys(line))
        self.assertFalse(revenue.filtered("earlydryer_analytic_gap"))

    def test_revenue_without_plant_in_gaps(self):
        income = self.company.earlydryer_laundry_income_account_id
        transit = self.company.earlydryer_cash_transit_account_id
        move = self.Move.create(
            {
                "move_type": "entry",
                "journal_id": self.company._earlydryer_misc_journal().id,
                "line_ids": [
                    Command.create(
                        {"account_id": income.id, "credit": 100.0, "name": "T"}
                    ),
                    Command.create(
                        {
                            "account_id": transit.id,
                            "debit": 100.0,
                            "name": "T",
                        }
                    ),
                ],
            }
        )
        move.action_post()
        line = move.line_ids.filtered(lambda l: l.account_id == income)
        self.assertTrue(line.earlydryer_analytic_gap)
        action = self.env.ref(
            "earlydryer_accounting_ng.action_earlydryer_analytic_gaps"
        )
        self.assertIn(
            line, self.MoveLine.search([("earlydryer_analytic_gap", "=", True)])
        )
        self.assertEqual(action.res_model, "account.move.line")
        line.analytic_distribution = {str(self.plant_1.id): 100.0}
        self.assertFalse(line.earlydryer_analytic_gap)
