# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.fields import Command
from odoo.tests import tagged

from .common import AccountingCommon


@tagged("post_install", "-at_install")
class TestVat(AccountingCommon):
    def _invoice(self, product, price, post=True):
        invoice = self.Move.create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "invoice_date": self.today,
                "earlydryer_branch_id": self.branch_1.id,
                "invoice_line_ids": [
                    Command.create(
                        {"product_id": product.id, "quantity": 1, "price_unit": price}
                    )
                ],
            }
        )
        if post:
            invoice.action_post()
        return invoice

    def test_vat_switch(self):
        company = self.company
        laundry = self.shirt_wi.product_tmpl_id
        self.assertFalse(company.earlydryer_vat_registered)
        vat_taxes = company._earlydryer_vat_sale_taxes()
        self.assertFalse(laundry.taxes_id & vat_taxes)
        before = self._invoice(self.shirt_wi, 1075.0)
        self.assertFalse(before.invoice_line_ids.tax_ids)

        company.earlydryer_vat_registered = True
        company.earlydryer_prices_include_vat = True
        company._earlydryer_apply_vat_setting()
        tax = company.earlydryer_sale_tax_id
        self.assertEqual(tax.amount, 7.5)
        self.assertTrue(tax.price_include)
        self.assertIn(tax, laundry.taxes_id)
        self.assertIn(tax, self.sur_beads.product_id.taxes_id)
        self.assertEqual(company.account_sale_tax_id, tax)
        # posted documents keep their taxes
        self.assertFalse(before.invoice_line_ids.tax_ids)
        self.assertEqual(before.amount_total, 1075.0)
        # price included on a new invoice
        after = self._invoice(self.shirt_wi, 1075.0)
        self.assertEqual(after.invoice_line_ids.tax_ids, tax)
        self.assertAlmostEqual(after.amount_untaxed, 1000.0)
        self.assertAlmostEqual(after.amount_tax, 75.0)
        self.assertAlmostEqual(after.amount_total, 1075.0)
        # safe to run again
        company._earlydryer_apply_vat_setting()
        self.assertEqual(laundry.taxes_id & company._earlydryer_vat_sale_taxes(), tax)

        # price excluded: the other tax, the included one is left untouched
        company.earlydryer_prices_include_vat = False
        company._earlydryer_apply_vat_setting()
        excluded = company.earlydryer_sale_tax_id
        self.assertNotEqual(excluded, tax)
        self.assertFalse(excluded.price_include)
        self.assertTrue(tax.price_include)
        self.assertEqual(
            laundry.taxes_id & company._earlydryer_vat_sale_taxes(), excluded
        )
        self.assertEqual(after.invoice_line_ids.tax_ids, tax)

        company.earlydryer_vat_registered = False
        company._earlydryer_apply_vat_setting()
        self.assertFalse(laundry.taxes_id & company._earlydryer_vat_sale_taxes())
        self.assertFalse(company.account_sale_tax_id)

    def test_vat_price_included_at_the_till(self):
        company = self.company
        company.earlydryer_vat_registered = True
        company._earlydryer_apply_vat_setting()
        tax = company.earlydryer_sale_tax_id
        line = self._line(self.shirt_wi, price=1075.0)
        line[2].update(
            {
                "tax_ids": [(6, 0, tax.ids)],
                "price_subtotal": 1000.0,
                "price_subtotal_incl": 1075.0,
            }
        )
        order = self._sync(self._payload([line], amount_tax=75.0))
        self.assertAlmostEqual(order.amount_total, 1075.0)
        session = order.session_id
        self._close_session(session)
        lines = session.move_id.line_ids
        revenue = lines.filtered(
            lambda l: l.account_id == company.earlydryer_laundry_income_account_id
        )
        tax_line = lines.filtered(lambda l: l.tax_line_id == tax)
        self.assertAlmostEqual(sum(revenue.mapped("balance")), -1000.0)
        self.assertAlmostEqual(sum(tax_line.mapped("balance")), -75.0)
