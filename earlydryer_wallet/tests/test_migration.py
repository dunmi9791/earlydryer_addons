# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64

from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.earlydryer_wallet.tools import normalize_ng_phone

from .common import WalletCommon

CSV = (
    "ref,name,phone,balance,branch_code,note\n"
    "M-1,T Wallet Customer,0803 000 0001,1500,TP1,page 1\n"
    "M-2,T Brand New,08099990000,2500,,page 2\n"
    "M-3,T Debtor,08099990001,-700,,page 3\n"
    "M-4,T Zero,08099990002,0,,page 4\n"
)


@tagged("post_install", "-at_install")
class TestMigration(WalletCommon):
    def _wizard(self, content=CSV, user=None):
        env = self.env(user=user) if user else self.env
        return env["earlydryer.wallet.import.wizard"].create(
            {
                "file": base64.b64encode(content.encode()),
                "filename": "balances.csv",
                "as_of_date": "2026-09-30",
            }
        )

    def test_phone_normalisation(self):
        self.assertEqual(normalize_ng_phone("0803 123 4567"), "+2348031234567")
        self.assertEqual(normalize_ng_phone("+234 803 123 4567"), "+2348031234567")
        self.assertEqual(normalize_ng_phone("2348031234567"), "+2348031234567")
        self.assertEqual(normalize_ng_phone("803-123-4567"), "+2348031234567")
        self.assertEqual(normalize_ng_phone(""), "")

    def test_dry_run_posts_nothing(self):
        wizard = self._wizard()
        moves = self.env["account.move"].search_count([])
        wizard.action_preview()
        self.assertEqual(wizard.state, "preview")
        by_ref = {line.ref: line for line in wizard.line_ids}
        self.assertEqual(by_ref["M-1"].status, "match")
        self.assertEqual(by_ref["M-1"].partner_id, self.customer)
        self.assertEqual(by_ref["M-1"].branch_id, self.branch_1)
        self.assertEqual(by_ref["M-2"].status, "create")
        self.assertEqual(by_ref["M-3"].status, "error")
        self.assertIn("opening receivables", by_ref["M-3"].message)
        self.assertEqual(by_ref["M-4"].status, "skip")
        self.assertEqual(wizard.total, 4000)
        self.assertEqual(self.env["account.move"].search_count([]), moves)
        self.assertFalse(self.Tx.search([("import_ref", "like", "M-")]))
        self.assertFalse(self.env["res.partner"].search([("name", "=", "T Brand New")]))

    def test_import_and_reimport(self):
        wizard = self._wizard()
        wizard.action_preview()
        wizard.action_import()
        self.assertEqual(wizard.state, "done")
        txs = self.Tx.search([("import_ref", "in", ["M-1", "M-2"])])
        self.assertEqual(len(txs), 2)
        self.assertEqual(set(txs.mapped("type")), {"migration"})
        self.assertEqual(txs.move_id, wizard.move_id)
        new = self.env["res.partner"].search([("name", "=", "T Brand New")])
        self.assertEqual(new.phone, "+2348099990000")
        self.assertEqual(self._balance(), 1500)
        self.assertEqual(self._balance(new), 2500)
        move = wizard.move_id
        opening = move.line_ids.filtered(lambda line: line.debit)
        self.assertEqual(
            opening.account_id, self.company.earlydryer_wallet_opening_account_id
        )
        self.assertEqual(opening.debit, 4000)
        advance_lines = move.line_ids.filtered(lambda line: line.credit)
        self.assertEqual(advance_lines.account_id, self.advances)
        self.assertEqual(set(advance_lines.partner_id.ids), {self.customer.id, new.id})
        # the same file again: nothing new
        again = self._wizard()
        again.action_preview()
        self.assertEqual(set(again.line_ids.mapped("status")), {"skip", "error"})
        self.assertEqual(again.count_match + again.count_create, 0)
        self.assertEqual(again.total, 0)
        self.assertEqual(len(self.Tx.search([("import_ref", "like", "M-")])), 2)

    def test_import_finance_only(self):
        for user in (self.user_front_desk, self.user_manager):
            with self.assertRaises(AccessError):
                self._wizard(user=user).action_preview()
