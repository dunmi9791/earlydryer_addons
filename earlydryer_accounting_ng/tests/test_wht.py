# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import Form, tagged
from odoo.tools.safe_eval import safe_eval

from .common import AccountingCommon


@tagged("post_install", "-at_install")
class TestWht(AccountingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.consultant = cls._vendor(
            "T Consultant", "earlydryer_accounting_ng.wht_category_professional"
        )
        cls.landlord = cls._vendor(
            "T Landlord", "earlydryer_accounting_ng.wht_category_rent", "individual"
        )
        cls.wht_account = cls.company.earlydryer_wht_payable_account_id
        cls.finance = cls.user_finance

    def test_bill_defaults_wht_and_vendor_paid_net(self):
        category = self.env.ref("earlydryer_accounting_ng.wht_category_professional")
        bill = self._bill(self.consultant, 100000.0)
        tax = bill.invoice_line_ids.tax_ids.filtered("earlydryer_wht_category_id")
        self.assertEqual(tax, category.tax_company_id)
        rate = category.rate_company_vendor
        wht = self._wht_lines(bill)
        self.assertEqual(wht.account_id, self.wht_account)
        self.assertAlmostEqual(wht.balance, -100000.0 * rate / 100)
        self.assertAlmostEqual(bill.amount_total, 100000.0 * (1 - rate / 100))
        self.assertAlmostEqual(bill.earlydryer_wht_amount, 100000.0 * rate / 100)
        # the individual rate for an individual vendor
        rent = self._bill(self.landlord, 50000.0)
        self.assertEqual(
            rent.invoice_line_ids.tax_ids.filtered("earlydryer_wht_category_id"),
            self.env.ref(
                "earlydryer_accounting_ng.wht_category_rent"
            ).tax_individual_id,
        )
        # paid net
        register = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=bill.ids)
            .create({"journal_id": self.bank_journal.id})
        )
        self.assertAlmostEqual(register.amount, bill.amount_total)
        payment = register._create_payments()
        self.assertEqual(bill.payment_state in ("paid", "in_payment"), True)
        self.assertAlmostEqual(
            payment.earlydryer_wht_amount, bill.earlydryer_wht_amount
        )

    def test_credit_note_reverses_wht(self):
        bill = self._bill(self.consultant, 100000.0)
        refund = bill._reverse_moves([{"invoice_date": self.today}])
        refund.action_post()
        self.assertAlmostEqual(
            sum(self._wht_lines(refund).mapped("balance")),
            -sum(self._wht_lines(bill).mapped("balance")),
        )

    def test_wht_removal_logged(self):
        bill = self._bill(self.consultant, 30000.0, post=False)
        line = bill.invoice_line_ids
        wht = line.tax_ids.filtered("earlydryer_wht_category_id")
        self.assertTrue(wht)
        with self.assertRaises(UserError):
            line.write({"tax_ids": [Command.unlink(wht.id)]})
        with self.assertRaises(UserError):
            line.with_user(self.user_front_desk)._earlydryer_remove_wht("exempt")
        wizard = (
            self.env["earlydryer.wht.removal.wizard"]
            .with_user(self.finance)
            .create({"move_id": bill.id, "reason": "Exempt supply of goods"})
        )
        self.assertEqual(wizard.line_ids, line)
        wizard.action_remove()
        self.assertFalse(line.tax_ids.filtered("earlydryer_wht_category_id"))
        self.assertIn("Exempt supply of goods", bill.message_ids[:1].body)

    def test_remittance_report_and_mark_remitted(self):
        bills = self._bill(self.consultant, 100000.0) | self._bill(
            self.landlord, 40000.0
        )
        report = self.env["earlydryer.wht.report.wizard"].create(
            {"date_from": self.today, "date_to": self.today}
        )
        ours = report.line_ids.filtered(lambda line: line.move_id in bills)
        self.assertEqual(len(ours), 2)
        rows = [row for row in report._earlydryer_rows() if row["line"] in ours]
        self.assertAlmostEqual(sum(row["base"] for row in rows), 140000.0)
        self.assertAlmostEqual(
            sum(row["wht"] for row in rows), sum(bills.mapped("earlydryer_wht_amount"))
        )
        self.assertEqual(
            {row["tin"] for row in rows}, {"TIN-T Consultant", "TIN-T Landlord"}
        )
        self.assertAlmostEqual(
            report.total_wht, sum(row["wht"] for row in report._earlydryer_rows())
        )
        # pdf and xlsx render
        self.env["ir.actions.report"]._render_qweb_pdf(
            "earlydryer_accounting_ng.action_report_wht_remittance", report.ids
        )
        self.env["ir.actions.report"]._render(
            "earlydryer_accounting_ng.action_report_wht_remittance_xlsx", report.ids
        )
        action = report.action_mark_remitted()
        remit = Form(
            self.env["earlydryer.wht.remit.wizard"].with_context(**action["context"])
        )
        remit.journal_id = self.bank_journal
        remit = remit.save()
        self.assertAlmostEqual(remit.amount, report.total_wht)
        remit.action_remit()
        self.assertTrue(all(ours.mapped("reconciled")))
        self.assertFalse(
            self.env["earlydryer.wht.report.wizard"]
            .create({"date_from": self.today, "date_to": self.today})
            .line_ids
        )

    def test_wht_receivable_deduction(self):
        invoice = self.Move.create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "invoice_date": self.today,
                "invoice_line_ids": [
                    Command.create(
                        {"product_id": self.shirt_wi.id, "price_unit": 20000.0}
                    )
                ],
            }
        )
        invoice.action_post()
        wizard = Form(
            self.env["earlydryer.wht.deduction.wizard"].with_context(
                default_invoice_id=invoice.id
            )
        )
        wizard.rate = 10
        wizard.reference = "T-CN-1"
        wizard = wizard.save()
        self.assertAlmostEqual(wizard.amount, 2000.0)
        wizard.action_register()
        self.assertAlmostEqual(invoice.amount_residual, 18000.0)
        self.assertAlmostEqual(invoice.earlydryer_wht_deducted, 2000.0)
        deduction = invoice.earlydryer_wht_deduction_ids
        receivable = deduction.line_ids.filtered(
            lambda l: l.account_id == self.company.earlydryer_wht_receivable_account_id
        )
        self.assertAlmostEqual(receivable.balance, 2000.0)
        action = self.env.ref(
            "earlydryer_accounting_ng.action_earlydryer_wht_awaiting_certificates"
        )
        awaiting = self.MoveLine.search(safe_eval(action.domain))
        self.assertIn(receivable, awaiting)
        deduction.action_earlydryer_wht_certificate_received()
        self.assertNotIn(receivable, self.MoveLine.search(safe_eval(action.domain)))
