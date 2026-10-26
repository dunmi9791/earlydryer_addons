# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import EarlydryerPosCommon


@tagged("post_install", "-at_install")
class TestDiscountApproval(EarlydryerPosCommon):
    def test_manager_pin_discount_logged(self):
        line = self._line(
            self.shirt_wi,
            discount=15.0,
            earlydryer_discount_approver_employee_id=self.emp_manager.id,
            earlydryer_discount_rule_id=self.rule_discount_bm.id,
        )
        order = self._sync(self._payload([line]))
        request = self.Request.search(
            [("res_model", "=", "pos.order"), ("res_id", "=", order.id)]
        )
        self.assertEqual(len(request), 1)
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.approval_type, "discount")
        self.assertEqual(request.rule_id, self.rule_discount_bm)
        self.assertEqual(request.value, 15.0)
        self.assertEqual(request.decided_by_id, self.user_manager)
        self.assertEqual(request.earlydryer_branch_id, self.branch_1)
        log = self.env["earlydryer.pos.pin.approval"].search(
            [("pos_order_id", "=", order.id)]
        )
        self.assertEqual(log.employee_id, self.emp_manager)
        self.assertEqual(log.user_id, self.user_manager)
        self.assertEqual(log.cashier_employee_id, self.emp_front_desk)
        self.assertEqual(log.pos_config_id, self.config)
        # the approval is checked like any other on the order
        self.assertTrue(
            self.Request._earlydryer_approval_check(
                "pos.order", order.id, "discount", 15.0, self.branch_1
            )
        )
        # the job item carries the discounted price
        self.assertEqual(order.earlydryer_job_id.item_ids.price_unit, 850)

    def test_employee_rule_lists(self):
        rules = self.rule_discount_fd | self.rule_discount_bm
        rule_ids = (self.emp_front_desk | self.emp_manager)._earlydryer_pos_rule_ids(
            rules
        )
        self.assertEqual(rule_ids[self.emp_front_desk.id], [self.rule_discount_fd.id])
        # a Branch Manager is also Front Desk (implied group)
        self.assertEqual(
            set(rule_ids[self.emp_manager.id]),
            {self.rule_discount_fd.id, self.rule_discount_bm.id},
        )
