# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import AccountingCommon


@tagged("post_install", "-at_install")
class TestSetup(AccountingCommon):
    def test_accounts_journals_and_methods(self):
        company = self.company
        for field in (
            "earlydryer_laundry_income_account_id",
            "earlydryer_retail_income_account_id",
            "earlydryer_delivery_income_account_id",
            "earlydryer_cash_diff_account_id",
            "earlydryer_cash_transit_account_id",
            "earlydryer_gateway_account_id",
            "earlydryer_wht_payable_account_id",
            "earlydryer_wht_receivable_account_id",
            "earlydryer_opening_journal_id",
            "earlydryer_gateway_journal_id",
        ):
            self.assertTrue(company[field], field)
        self.assertTrue(company.earlydryer_wht_payable_account_id.reconcile)
        for branch in self.branch_1 | self.branch_2:
            cash = branch.cash_journal_id
            self.assertEqual(cash.type, "cash")
            self.assertEqual(cash.earlydryer_branch_id, branch)
            self.assertEqual(cash.default_account_id.account_type, "asset_cash")
            self.assertEqual(
                cash.loss_account_id, company.earlydryer_cash_diff_account_id
            )
            rider = branch.earlydryer_rider_journal_id
            self.assertEqual(rider.type, "cash")
            self.assertTrue(rider.default_account_id.reconcile)
            self.assertTrue(branch.analytic_account_id)
        self.assertEqual(self.bank_journal.earlydryer_role, "bank")
        self.assertFalse(self.bank_journal.earlydryer_branch_id)
        # tills: plant cash, card clearing, bank transfer, customer account kept
        for config in self.config | self.config_2:
            journals = config.payment_method_ids.journal_id
            self.assertIn(config.earlydryer_branch_id.cash_journal_id, journals)
            self.assertIn(self.bank_journal, journals)
            self.assertTrue(journals.filtered(lambda j: j.earlydryer_role == "card"))
            self.assertIn(self.pm_account, config.payment_method_ids)
        card = self.config.payment_method_ids.filtered(
            lambda m: m.journal_id.earlydryer_role == "card"
        )
        self.assertEqual(
            card.outstanding_account_id, card.journal_id.default_account_id
        )
        # the replaced cash method is unlinked from the till, never deleted
        self.assertTrue(self.pm_cash.exists())
        self.assertNotIn(self.pm_cash, self.config.payment_method_ids)
        self.assertTrue(self.setup.pos_line_ids)
        # fiscal year and periods
        self.assertEqual(company.fiscalyear_last_month, "12")
        self.assertEqual(company.fiscalyear_last_day, 31)
        self.assertTrue(
            self.env["account.fiscal.year"].search_count(
                [
                    ("company_id", "=", company.id),
                    ("date_from", "=", f"{self.today.year}-01-01"),
                ]
            )
        )

    def test_rerun_creates_nothing(self):
        counts = {
            model: self.env[model].with_context(active_test=False).search_count([])
            for model in (
                "account.account",
                "account.journal",
                "account.tax",
                "pos.payment.method",
                "account.analytic.account",
                "account.analytic.distribution.model",
                "date.range",
                "mis.report.instance",
            )
        }
        wizard = self._run_setup()
        self.assertEqual(wizard.created_count, 0)
        self.assertFalse(
            wizard.line_ids.filtered(lambda line: line.status in ("create", "done"))
        )
        for model, count in counts.items():
            self.assertEqual(
                self.env[model].with_context(active_test=False).search_count([]),
                count,
                model,
            )

    def test_existing_account_reused_by_code(self):
        existing = self.env["account.account"].create(
            {
                "name": "T rider cash kept by the accountant",
                "code": "T9911",
                "account_type": "asset_current",
                "reconcile": True,
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "earlydryer_accounting_ng.code_rider_cash", "T9911"
        )
        branch = self.Branch.create({"name": "Test Plant 3", "code": "TP3"})
        wizard = self._run_setup()
        line = wizard.line_ids.filtered(
            lambda l: l.key == f"acc_rider_cash_{branch.id}"
        )
        self.assertEqual(line.status, "reuse")
        self.assertEqual(
            branch.earlydryer_rider_journal_id.default_account_id, existing
        )

    def test_customer_advances_never_duplicated(self):
        advances = self.company.earlydryer_wallet_account_id
        self.assertTrue(advances)
        self._run_setup()
        self.assertEqual(self.company.earlydryer_wallet_account_id, advances)
        self.assertEqual(
            self.env["account.account"].search_count(
                [("name", "=", advances.name), ("company_ids", "in", self.company.ids)]
            ),
            1,
        )
        line = self.setup.line_ids.filtered(lambda l: l.key == "acc_advances")
        self.assertEqual(line.status, "reuse")

    def test_default_rerun_adds_no_card_journal(self):
        """The wizard opened with its defaults adds no card provider when the
        company already has a card clearing journal."""
        cards = self.env["account.journal"].search_count(
            [("earlydryer_role", "=", "card")]
        )
        wizard = self.Wizard.create({})
        self.assertFalse(wizard.card_providers)
        wizard._earlydryer_run()
        self.assertEqual(wizard.created_count, 0)
        self.assertEqual(
            self.env["account.journal"].search_count(
                [("earlydryer_role", "=", "card")]
            ),
            cards,
        )
