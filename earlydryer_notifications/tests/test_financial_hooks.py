# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields
from odoo.addons.earlydryer_wallet.tests.common import WalletCommon
from odoo.addons.queue_job.tests.common import trap_jobs
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestFinancialHooks(WalletCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["earlydryer.notify.provider"].search(
            [("active", "=", True)]
        ).active = False
        cls.env["earlydryer.notify.provider"].create(
            {
                "name": "Financial test",
                "channel": "whatsapp",
                "provider_type": "log_only",
            }
        )
        cls.Messages = cls.env["earlydryer.notify.message"]

    def setUp(self):
        super().setUp()
        self.enterContext(trap_jobs())

    def test_wallet_topup_event(self):
        tx = self._topup(2000)
        message = self.Messages.search(
            [
                ("event_id.code", "=", "wallet_topup"),
                ("res_model", "=", tx._name),
                ("res_id", "=", tx.id),
            ]
        )
        self.assertEqual(len(message), 1)
        self.assertIn("2000", message.body)
        self.assertEqual(tx.state, "posted")
        self.assertEqual(
            self.branch_1._earlydryer_eod_figures(fields.Date.today())["wallet_topups"],
            2000,
        )

    def test_payment_event_and_template_failure(self):
        template = self.env.ref(
            "earlydryer_notifications.template_payment_received_whatsapp"
        )
        template.body = "{{ object.missing_payment_field }}"
        tx = self._topup(3000)
        self.assertEqual(tx.state, "posted")
        errors = self.Messages.search(
            [
                ("res_model", "=", "account.payment"),
                ("res_id", "=", tx.payment_id.id),
                ("state", "=", "failed"),
            ]
        )
        self.assertTrue(errors)

    def test_pos_sync_payment_event(self):
        payload = self._wallet_payload(
            [self._line(self.shirt_wi, 1)], partner=self.customer
        )
        order = self._sync(payload)
        self.assertEqual(order.state, "paid")
        self.assertTrue(
            self.Messages.search(
                [
                    ("event_id.code", "=", "payment_received"),
                    ("res_model", "=", "pos.order"),
                    ("res_id", "=", order.id),
                ]
            )
        )

    def test_pos_sync_survives_broken_template(self):
        self.env.ref(
            "earlydryer_notifications.template_job_received_whatsapp"
        ).body = "{{ object.no_such_field }}"
        order = self._sync(
            self._wallet_payload([self._line(self.shirt_wi, 1)], partner=self.customer)
        )
        self.assertEqual(order.state, "paid")
        self.assertTrue(order.earlydryer_job_id)
        self.assertFalse(order.earlydryer_job_error)
