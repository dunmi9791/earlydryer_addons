# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import EarlydryerCommon


@tagged("post_install", "-at_install")
class TestApproval(EarlydryerCommon):
    """The approval engine, tested on res.partner documents.

    res.partner has no earlydryer_branch_id, so the branch is passed
    explicitly, as the mixin does for documents that have one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["earlydryer.approval.request"]
        cls.Rule = cls.env["earlydryer.approval.rule"]
        cls.partner_model_id = cls.env["ir.model"]._get_id("res.partner")
        cls.group_bm = cls.env.ref("earlydryer_base.group_branch_manager")
        cls.group_mgmt = cls.env.ref("earlydryer_base.group_management")
        # isolate from demo rules
        cls.Rule.search([]).active = False
        cls.rule_bm = cls.Rule.create(
            {
                "name": "Discount up to 5%",
                "sequence": 10,
                "approval_type": "discount",
                "model_id": cls.partner_model_id,
                "threshold_kind": "percent",
                "min_value": 0,
                "max_value": 5,
                "approver_group_id": cls.group_bm.id,
                "self_approve": True,
            }
        )
        cls.rule_mgmt = cls.Rule.create(
            {
                "name": "Discount above 5%",
                "sequence": 20,
                "approval_type": "discount",
                "model_id": cls.partner_model_id,
                "threshold_kind": "percent",
                "min_value": 5,
                "approver_group_id": cls.group_mgmt.id,
            }
        )
        cls.rule_credit_p2 = cls.Rule.create(
            {
                "name": "Credit on P2",
                "approval_type": "credit",
                "model_id": cls.partner_model_id,
                "threshold_kind": "amount",
                "branch_ids": [(6, 0, cls.branch_2.ids)],
                "approver_group_id": cls.group_bm.id,
            }
        )
        cls.front_desk = cls._new_user(
            "ed_t_ap_frontdesk", "earlydryer_base.group_front_desk", cls.branch_1
        )
        cls.bm_p1 = cls._new_user(
            "ed_t_ap_bm1", "earlydryer_base.group_branch_manager", cls.branch_1
        )
        cls.bm_p2 = cls._new_user(
            "ed_t_ap_bm2", "earlydryer_base.group_branch_manager", cls.branch_2
        )
        cls.management = cls._new_user(
            "ed_t_ap_mgmt", "earlydryer_base.group_management"
        )
        cls.partner = cls.env["res.partner"].create({"name": "Customer A"})

    def _check(self, user, approval_type, value, branch=None):
        return self.Request.with_user(user)._earlydryer_approval_check(
            "res.partner",
            self.partner.id,
            approval_type,
            value,
            branch or self.branch_1,
        )

    def _request(
        self, user, approval_type, value, branch=None, reason="Loyal customer"
    ):
        return self.Request.with_user(user)._earlydryer_request_approval(
            "res.partner",
            self.partner.id,
            approval_type,
            value,
            reason,
            branch or self.branch_1,
        )

    def test_rule_matching_by_range(self):
        match = self.Request._earlydryer_approval_rule
        self.assertFalse(match("res.partner", "discount", 0, self.branch_1))
        self.assertEqual(
            match("res.partner", "discount", 3, self.branch_1), self.rule_bm
        )
        self.assertEqual(
            match("res.partner", "discount", 5, self.branch_1), self.rule_bm
        )
        self.assertEqual(
            match("res.partner", "discount", 5.5, self.branch_1), self.rule_mgmt
        )
        self.assertEqual(
            match("res.partner", "discount", 80, self.branch_1), self.rule_mgmt
        )
        self.assertFalse(match("res.users", "discount", 3, self.branch_1))

    def test_rule_matching_by_branch(self):
        match = self.Request._earlydryer_approval_rule
        self.assertFalse(match("res.partner", "credit", 1000, self.branch_1))
        self.assertEqual(
            match("res.partner", "credit", 1000, self.branch_2), self.rule_credit_p2
        )
        self.assertFalse(match("res.partner", "credit", 1000, None))

    def test_no_rule_means_approved(self):
        self.assertTrue(self._check(self.front_desk, "claim", 999))
        self.assertTrue(self._check(self.front_desk, "credit", 1000, self.branch_1))
        self.Request.with_user(self.front_desk)._earlydryer_approval_ensure(
            "res.partner", self.partner.id, "claim", 999, self.branch_1
        )

    def test_rule_constraints(self):
        with self.assertRaises(UserError):
            self.rule_bm.max_value = -1
        with self.assertRaises(UserError):
            self.rule_bm.write({"min_value": 10, "max_value": 5})
        with self.assertRaises(UserError):
            self.rule_mgmt.min_value = 150

    def test_check_fails_and_ensure_raises(self):
        self.assertFalse(self._check(self.front_desk, "discount", 10))
        with self.assertRaisesRegex(UserError, "Management"):
            self.Request.with_user(self.front_desk)._earlydryer_approval_ensure(
                "res.partner", self.partner.id, "discount", 10, self.branch_1
            )

    def test_request_schedules_activities_for_branch_approvers(self):
        request = self._request(self.front_desk, "discount", 4)
        self.assertEqual(request.state, "pending")
        self.assertTrue(request.name.startswith("EDA/"))
        self.assertEqual(request.requested_by_id, self.front_desk)
        approvers = request.approver_user_ids
        self.assertIn(self.bm_p1, approvers)
        self.assertNotIn(self.bm_p2, approvers)
        # management has all branches, and implies branch manager
        self.assertIn(self.management, approvers)
        self.assertNotIn(self.front_desk, approvers)
        activity_users = request.activity_ids.user_id
        self.assertIn(self.bm_p1, activity_users)
        self.assertNotIn(self.bm_p2, activity_users)
        # requester and approver can read it, other branch manager cannot
        request.with_user(self.front_desk).read(["state"])
        request.with_user(self.bm_p1).read(["state"])
        with self.assertRaises(AccessError):
            request.with_user(self.bm_p2).read(["state"])

    def test_request_falls_back_to_all_group_users(self):
        branch_3 = self.Branch.create({"name": "Test Plant 3", "code": "TP3"})
        group = self.env["res.groups"].create({"name": "Test approvers"})
        approver = self._new_user("ed_t_ap_other", "base.group_user", self.branch_1)
        approver.group_ids = [(4, group.id)]
        self.rule_mgmt.approver_group_id = group
        request = self._request(self.front_desk, "discount", 50, branch_3)
        self.assertEqual(request.approver_user_ids, approver)

    def test_approve_restricted_to_approver_group(self):
        request = self._request(self.front_desk, "discount", 10)
        with self.assertRaises(AccessError):
            request.with_user(self.front_desk).action_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.bm_p1).action_approve()
        self.assertFalse(self._check(self.front_desk, "discount", 10))
        request.with_user(self.management).action_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.decided_by_id, self.management)
        self.assertTrue(request.decided_on)
        self.assertFalse(request.activity_ids)
        # approved for 10%: 10% and less pass, more does not
        self.assertTrue(self._check(self.front_desk, "discount", 10))
        self.assertTrue(self._check(self.front_desk, "discount", 8))
        self.assertFalse(self._check(self.front_desk, "discount", 12))
        with self.assertRaises(UserError):
            request.with_user(self.management).action_reject()

    def test_reject_and_cancel(self):
        request = self._request(self.front_desk, "discount", 10)
        with self.assertRaises(AccessError):
            request.with_user(self.front_desk).action_reject()
        request.with_user(self.management).action_reject()
        self.assertEqual(request.state, "rejected")
        self.assertFalse(self._check(self.front_desk, "discount", 10))
        request = self._request(self.front_desk, "discount", 10)
        with self.assertRaises(AccessError):
            request.with_user(self.bm_p2).action_cancel()
        request.with_user(self.front_desk).action_cancel()
        self.assertEqual(request.state, "cancelled")

    def test_self_approve(self):
        self.assertTrue(self._check(self.bm_p1, "discount", 4))
        request = self.Request.search(
            [("res_model", "=", "res.partner"), ("res_id", "=", self.partner.id)]
        )
        self.assertEqual(len(request), 1)
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.decided_by_id, self.bm_p1)
        self.assertEqual(request.rule_id, self.rule_bm)
        # no self-approval on the management rule
        self.assertFalse(self._check(self.bm_p1, "discount", 6))

    def test_duplicate_pending_refused(self):
        self._request(self.front_desk, "discount", 10)
        with self.assertRaises(UserError):
            self._request(self.front_desk, "discount", 12)
        # another type is fine
        self._request(self.front_desk, "credit", 100, self.branch_2)

    def test_requester_cannot_tamper(self):
        request = self._request(self.front_desk, "discount", 10)
        with self.assertRaises(UserError):
            request.with_user(self.front_desk).write({"state": "approved"})
        forged = self.Request.with_user(self.front_desk).create(
            {
                "rule_id": self.rule_mgmt.id,
                "res_model": "res.partner",
                "res_id": self.env["res.partner"].create({"name": "B"}).id,
                "value": 50,
                "reason": "forged",
                "state": "approved",
            }
        )
        self.assertEqual(forged.state, "pending")

    def test_wizard(self):
        wizard = (
            self.env["earlydryer.approval.request.wizard"]
            .with_user(self.front_desk)
            .create(
                {
                    "res_model": "res.partner",
                    "res_id": self.partner.id,
                    "approval_type": "discount",
                    "value": 30,
                    "reason": "Corporate client",
                }
            )
        )
        wizard.action_request()
        request = self.Request.search(
            [("res_model", "=", "res.partner"), ("res_id", "=", self.partner.id)]
        )
        self.assertEqual(request.rule_id, self.rule_mgmt)
        self.assertEqual(request.reason, "Corporate client")
        self.assertEqual(request.res_name, "Customer A")
        self.assertTrue(
            self.partner.message_ids.filtered(lambda m: request.name in (m.body or ""))
        )
