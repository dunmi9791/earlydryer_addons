# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import tagged

from .common import AccountingCommon


@tagged("post_install", "-at_install")
class TestCloseAccess(AccountingCommon):
    def _checklist(self):
        return (
            self.env["earlydryer.close.checklist"]
            .with_user(self.user_finance)
            .create({"date_from": self.today.replace(day=1), "date_to": self.today})
        )

    def _line(self, checklist, code):  # pylint: disable=arguments-differ
        return checklist.line_ids.filtered(lambda line: line.check_code == code)

    def test_checklist_lines_and_checks(self):
        checklist = self._checklist()
        self.assertEqual(len(checklist.line_ids), 9)
        # open session
        self._open_session(self.config)
        line = self._line(checklist, "pos_closed")
        line.action_check()
        self.assertEqual(line.status, "issue")
        self.assertIn(self.config.current_session_id.name, line.status_message)
        # unreconciled clearing line (cash in transit after a lodgement)
        lodgement = self.env["earlydryer.cash.lodgement.wizard"].create(
            {"branch_id": self.branch_1.id, "bank_journal_id": self.bank_journal.id}
        )
        lodgement.amount = 10.0
        lodgement.below_float = False
        self.Move._earlydryer_rider_handover(
            self.branch_1, 100.0, self.env["hr.employee"]
        )
        lodgement._earlydryer_lodge()
        line = self._line(checklist, "clearing_reconciled")
        line.action_check()
        self.assertEqual(line.status, "issue")
        # wallet control difference: an entry on the advances account without wallet
        advances = self.company.earlydryer_wallet_account_id
        move = self.Move.create(
            {
                "move_type": "entry",
                "journal_id": self.company._earlydryer_misc_journal().id,
                "line_ids": [
                    Command.create(
                        {"account_id": advances.id, "credit": 123.0, "name": "T"}
                    ),
                    Command.create(
                        {
                            "account_id": self.company.expense_account_id.id,
                            "debit": 123.0,
                            "name": "T",
                            "analytic_distribution": {
                                str(self.branch_1.analytic_account_id.id): 100
                            },
                        }
                    ),
                ],
            }
        )
        move.action_post()
        line = self._line(checklist, "wallet_control")
        line.action_check()
        self.assertEqual(line.status, "issue")
        # VAT return not applicable when not registered; lock date opens the OCA wizard
        line = self._line(checklist, "vat_return")
        line.action_check()
        self.assertEqual(line.status, "na")
        action = self._line(checklist, "lock_date").action_open_tool()
        self.assertEqual(action["res_model"], "account.update.lock_date")
        checklist.action_check_all()
        line = self._line(checklist, "pos_closed")
        line.done = True
        self.assertEqual(line.done_by_id, self.user_finance)
        with self.assertRaises(AccessError):
            self.env["earlydryer.close.checklist"].with_user(
                self.user_branch_manager
            ).create({"date_from": self.today, "date_to": self.today})

    def test_front_desk_access(self):
        with self.assertRaises(AccessError):
            self.Wizard.with_user(self.user_front_desk).action_open()
        with self.assertRaises(AccessError):
            self.Wizard.with_user(self.user_front_desk).create({})
        Journal = self.env["account.journal"].with_user(self.user_front_desk)
        own = self.branch_1.cash_journal_id
        other = self.branch_2.cash_journal_id
        visible = Journal.search([("id", "in", (own | other | self.bank_journal).ids)])
        self.assertIn(own, visible)
        self.assertIn(self.bank_journal, visible)
        self.assertNotIn(other, visible)
        # finance sees every plant
        visible = (
            self.env["account.journal"]
            .with_user(self.user_finance)
            .search([("id", "in", (own | other).ids)])
        )
        self.assertEqual(visible, own | other)
        with self.assertRaises(AccessError):
            self.env["earlydryer.wht.category"].with_user(
                self.user_branch_manager
            ).create({"name": "T", "code": "TX"})
