# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import WalletCommon


@tagged("post_install", "-at_install")
class TestRefundCredit(WalletCommon):
    def _refund(self, amount, user):
        wizard = (
            self.env["earlydryer.wallet.refund.wizard"]
            .with_user(user)
            .create(
                {
                    "partner_id": self.customer.id,
                    "amount": amount,
                    "journal_id": self.journal_cash.id,
                    "reason": "T customer moves away",
                }
            )
        )
        action = wizard.action_confirm()
        return self.Tx.browse(action["res_id"])

    def _credit(self, amount, user):
        wizard = (
            self.env["earlydryer.wallet.credit.wizard"]
            .with_user(user)
            .create(
                {
                    "partner_id": self.customer.id,
                    "amount": amount,
                    "reason": "T goodwill",
                }
            )
        )
        action = wizard.action_confirm()
        return self.Tx.browse(action["res_id"])

    def test_refund_waits_for_approval_then_posts(self):
        self._topup(6000)
        tx = self._refund(2000, self.user_front_desk)
        self.assertEqual(tx.state, "draft")
        self.assertFalse(tx.move_id)
        self.assertEqual(self._balance(), 6000)
        request = tx.earlydryer_approval_request_ids
        self.assertEqual(request.state, "pending")
        self.assertEqual(
            request.approver_group_id, self.env.ref("earlydryer_base.group_management")
        )
        request.with_user(self.user_management).action_approve()
        self.assertEqual(tx.state, "posted")
        self.assertEqual(self._balance(), 4000)
        lines = tx.move_id.line_ids
        self.assertEqual(
            lines.filtered(lambda line: line.debit).account_id, self.advances
        )
        self.assertEqual(
            lines.filtered(lambda line: line.credit).account_id,
            self.journal_cash.default_account_id,
        )
        self.assertEqual(self._gl_delta(), 4000)

    def test_refund_rejected_is_cancelled(self):
        self._topup(6000)
        tx = self._refund(2000, self.user_front_desk)
        tx.earlydryer_approval_request_ids.with_user(
            self.user_management
        ).action_reject()
        self.assertEqual(tx.state, "cancelled")
        self.assertEqual(self._balance(), 6000)

    def test_refund_no_self_approval(self):
        """The refund rule has no self-approval: Management requesting waits
        for another manager."""
        self._topup(6000)
        tx = self._refund(1000, self.user_management)
        self.assertEqual(tx.state, "draft")
        tx.earlydryer_approval_request_ids.with_user(
            self.user_management_2
        ).action_approve()
        self.assertEqual(tx.state, "posted")

    def test_credit_self_approved_by_branch_manager(self):
        tx = self._credit(5000, self.user_manager)
        self.assertEqual(tx.state, "posted")
        self.assertEqual(self._balance(), 5000)
        debit = tx.move_id.line_ids.filtered(lambda line: line.debit)
        self.assertEqual(
            debit.account_id, self.company.earlydryer_wallet_credit_account_id
        )
        credit = tx.move_id.line_ids.filtered(lambda line: line.credit)
        self.assertEqual(credit.account_id, self.advances)
        self.assertEqual(credit.partner_id, self.customer)
        self.assertEqual(tx.earlydryer_approval_request_ids.state, "approved")

    def test_credit_from_customer_service_needs_approval(self):
        tx = self._credit(5000, self.user_cs)
        self.assertEqual(tx.state, "draft")
        request = tx.earlydryer_approval_request_ids
        request.with_user(self.user_manager).action_approve()
        self.assertEqual(tx.state, "posted")
        self.assertEqual(self._balance(), 5000)

    def test_large_credit_needs_management(self):
        tx = self._credit(20000, self.user_manager)
        self.assertEqual(tx.state, "draft")
        request = tx.earlydryer_approval_request_ids
        self.assertEqual(
            request.approver_group_id, self.env.ref("earlydryer_base.group_management")
        )
        request.with_user(self.user_management).action_approve()
        self.assertEqual(tx.state, "posted")

    def test_refund_approved_after_balance_spent_stays_draft(self):
        self._topup(3000)
        tx = self._refund(3000, self.user_front_desk)
        self._invoice(3000)._earlydryer_wallet_spend(3000)
        tx.earlydryer_approval_request_ids.with_user(
            self.user_management
        ).action_approve()
        self.assertEqual(tx.state, "draft")
        self.assertEqual(self._balance(), 0)
