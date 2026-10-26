# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..models.earlydryer_tablet_identification import MAX_FAILURES
from .common import ProductionCommon


@tagged("post_install", "-at_install")
class TestIdentify(ProductionCommon):
    def _identify(self, code, branch=None, user=None, key="tablet-1"):
        Employee = self.Employee.with_user(user or self.user_production)
        return Employee._earlydryer_identify(
            code, (branch or self.branch_1).id, session_key=key
        )

    def test_badge_and_pin_match_branch_staff(self):
        employee, ident = self._identify("TBADGE-1")
        self.assertEqual(employee, self.employee)
        self.assertEqual((ident.result, ident.method), ("ok", "badge"))
        self.assertTrue(ident.sudo().token)
        employee, ident = self._identify("1234")
        self.assertEqual((employee, ident.method), (self.employee, "pin"))
        # employees without a plant match everywhere
        self.assertEqual(self._identify("TBADGE-F")[0], self.employee_floating)
        # another plant's badge or PIN does not
        with self.assertRaises(UserError):
            self._identify("TBADGE-2")
        with self.assertRaises(UserError):
            self._identify("5678")

    def test_branch_access_and_mode(self):
        with self.assertRaises(AccessError):
            self._identify("TBADGE-2", branch=self.branch_2)
        self.branch_1.production_mode = "front_desk"
        with self.assertRaises(UserError):
            self._identify("TBADGE-1")

    def _fail(self, code, key="tablet-1"):
        # like the RPC wrapper: no savepoint, so the failed attempt stays logged
        try:
            self._identify(code, key=key)
        except UserError as error:
            return str(error)
        self.fail(f"{code} was accepted")

    def test_pin_lockout(self):
        for _attempt in range(MAX_FAILURES):
            self._fail("0000")
        failed = self.Ident.search([("result", "=", "failed")])
        self.assertEqual(len(failed), MAX_FAILURES)
        # locked: even the right PIN is refused, other tablets are not
        self.assertIn("locked", self._fail("1234"))
        self.assertEqual(self._identify("1234", key="tablet-2")[0], self.employee)
        # after the lock time the tablet works again
        failed.write({"date": fields.Datetime.now() - timedelta(minutes=3)})
        self.assertEqual(self._identify("1234")[0], self.employee)

    def test_rpc_logs_failures(self):
        res = self.Job.with_user(self.user_production).earlydryer_tablet_identify(
            "nope", self.branch_1.id
        )
        self.assertFalse(res["ok"])
        self.assertEqual(
            self.Ident.search([], limit=1).employee_id, self.Employee.browse()
        )

    def test_idle_timeout(self):
        _employee, ident = self._identify("TBADGE-1")
        token = ident.sudo().token
        Ident = self.Ident.with_user(self.user_production)
        self.assertEqual(
            Ident._earlydryer_check_token(token, self.branch_1), self.employee
        )
        # refreshed by each use, refused once idle longer than the plant setting
        self.branch_1.tablet_idle_seconds = 120
        ident.sudo().last_activity = fields.Datetime.now() - timedelta(seconds=60)
        Ident._earlydryer_check_token(token, self.branch_1)
        ident.sudo().last_activity = fields.Datetime.now() - timedelta(seconds=121)
        with self.assertRaisesRegex(UserError, "idle"):
            Ident._earlydryer_check_token(token, self.branch_1)
        self.assertTrue(ident.ended)
        with self.assertRaises(UserError):
            Ident._earlydryer_check_token(token, self.branch_1)
        # another tablet user cannot reuse the token
        _employee, ident = self._identify("TBADGE-1")
        with self.assertRaises(UserError):
            self.Ident.with_user(self.user_qc)._earlydryer_check_token(
                ident.sudo().token, self.branch_1
            )

    def test_badge_report(self):
        action = self.employee.action_print_earlydryer_badge()
        self.assertEqual(action["type"], "ir.actions.report")
        html = self.env["ir.actions.report"]._render_qweb_html(
            "earlydryer_production.report_employee_badge", self.employee.ids
        )[0]
        self.assertIn(b"TBADGE-1", html)
