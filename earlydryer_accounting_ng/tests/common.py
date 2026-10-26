# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields
from odoo.fields import Command

from odoo.addons.earlydryer_pos.tests.common import EarlydryerPosCommon


class AccountingCommon(EarlydryerPosCommon):
    """The POS test plants and tills, after the accounting setup."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Move = cls.env["account.move"]
        cls.MoveLine = cls.env["account.move.line"]
        cls.Wizard = cls.env["earlydryer.accounting.setup.wizard"]
        cls.setup = cls._run_setup()
        cls.branch_1.earlydryer_cash_float = 1000.0
        cls.branch_2.earlydryer_cash_float = 1000.0
        cls.bank_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("earlydryer_role", "=", "bank"),
                ("name", "=", "T Bank T-999000111"),
            ],
            limit=1,
        )
        cls.user_branch_manager = cls.user_manager
        cls.today = fields.Date.context_today(cls.Move)

    @classmethod
    def _run_setup(cls, **vals):
        wizard = cls.Wizard.create(
            {
                "bank_name": "T Bank",
                "bank_acc_number": "T-999000111",
                "card_providers": "T Terminals",
                **vals,
            }
        )
        wizard._earlydryer_run()
        return wizard

    @classmethod
    def _vendor(cls, name, category_xmlid, vendor_type="company"):
        return cls.env["res.partner"].create(
            {
                "name": name,
                "is_company": vendor_type == "company",
                "vat": f"TIN-{name}",
                "earlydryer_wht_category_id": cls.env.ref(category_xmlid).id,
                "earlydryer_wht_vendor_type": vendor_type,
            }
        )

    def _bill(self, partner, amount, move_type="in_invoice", post=True, branch=None):
        bill = self.Move.create(
            {
                "move_type": move_type,
                "partner_id": partner.id,
                "invoice_date": self.today,
                "earlydryer_branch_id": (branch or self.branch_1).id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "T service",
                            "quantity": 1,
                            "price_unit": amount,
                            "account_id": self.company.expense_account_id.id,
                        }
                    )
                ],
            }
        )
        if post:
            bill.action_post()
        return bill

    def _wht_lines(self, move):
        return move.line_ids.filtered(
            lambda line: line.tax_line_id.earlydryer_wht_category_id
        )
