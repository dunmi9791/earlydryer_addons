# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import ReportingCommon


@tagged("post_install", "-at_install")
class TestPacks(ReportingCommon):
    def subscription(self, frequency="weekly", user=None):
        user = user or self.user_management
        return self.env["earlydryer.report.subscription"].create(
            {
                "user_id": user.id,
                "owner_user_id": user.id,
                "company_id": self.env.company.id,
                "frequency": frequency,
                "send_time": 0,
                "branch_ids": [(6, 0, self.branch_1.ids)],
            }
        )

    def test_due_once_and_previous_complete_period(self):
        sub = self.subscription()
        self.env["earlydryer.report.subscription"]._cron_due()
        self.env["earlydryer.report.subscription"]._cron_due()
        packs = self.env["earlydryer.report.pack"].search(
            [("subscription_id", "=", sub.id)]
        )
        self.assertEqual(len(packs), 1)
        self.assertEqual((packs.date_to - packs.date_from).days, 6)
        self.assertEqual(packs.date_from.weekday(), 0)

    def test_send_now_explicit_period(self):
        sub = self.subscription()
        wizard = self.env["earlydryer.report.send.wizard"].create(
            {"subscription_id": sub.id, "date_from": self.start, "date_to": self.end}
        )
        wizard.action_send()
        wizard.action_send()
        packs = self.env["earlydryer.report.pack"].search(
            [("subscription_id", "=", sub.id)]
        )
        self.assertEqual(len(packs), 2)
        self.assertEqual(packs.mapped("date_from"), [self.start, self.start])

    def test_defaults_and_home_action_preservation(self):
        self.env["earlydryer.report.subscription"]._defaults()
        subscriptions = self.env["earlydryer.report.subscription"].search(
            [("user_id", "=", self.user_management.id)]
        )
        self.assertEqual(set(subscriptions.mapped("frequency")), {"weekly", "monthly"})
        daily = self.env["earlydryer.report.subscription"].search(
            [("user_id", "=", self.user_manager.id)]
        )
        self.assertEqual(daily.frequency, "daily")
        self.assertEqual(daily.branch_ids, self.branch_1)
        self.env["earlydryer.report.subscription"]._defaults()
        self.assertEqual(
            len(
                self.env["earlydryer.report.subscription"].search(
                    [("user_id", "=", self.user_manager.id)]
                )
            ),
            1,
        )

    def test_monthly_mis_exports_and_email_queue(self):
        sub = self.subscription("monthly")
        self.user_management.partner_id.email = "report@example.invalid"
        pack = self.env["earlydryer.report.pack"]._schedule(sub, self.start, self.end)
        with patch.object(
            type(self.env["ir.actions.report"]),
            "_render_qweb_pdf",
            return_value=(b"%PDF-test", "pdf"),
        ):
            pack._deliver()
        self.assertEqual(pack.state, "done")
        self.assertEqual(len(pack.attachment_ids), 5)
        self.assertEqual(len(pack.mis_instance_ids), 2)
        self.assertEqual(
            len(pack.attachment_ids.filtered(lambda a: a.name.endswith(".xlsx"))), 2
        )
        mail = self.env["mail.mail"].search(
            [("attachment_ids", "in", pack.attachment_ids.ids)]
        )
        self.assertEqual(mail.state, "outgoing")
        self.assertEqual(len(mail.attachment_ids), 5)

    def test_own_subscription_guard(self):
        sub = self.subscription(user=self.user_manager)
        with self.assertRaises(AccessError):
            sub.with_user(self.user_manager).write({"user_id": self.user_management.id})
        with self.assertRaises(AccessError):
            self.env["earlydryer.report.subscription"].with_user(
                self.user_manager
            ).create({"user_id": self.user_management.id})

    def test_recipient_cannot_select_other_plant(self):
        sub = self.subscription(user=self.user_manager)
        with self.assertRaises(AccessError):
            sub.with_user(self.user_manager).write(
                {"branch_ids": [(6, 0, self.branch_2.ids)]}
            )

    def test_daily_not_enqueued_as_second_pack(self):
        sub = self.subscription("daily", self.user_manager)
        self.env["earlydryer.report.subscription"]._cron_due()
        self.assertFalse(
            self.env["earlydryer.report.pack"].search(
                [("subscription_id", "=", sub.id)]
            )
        )

    def test_branch_manager_monthly_pack_stays_scoped(self):
        sub = self.subscription("monthly", self.user_manager)
        pack = self.env["earlydryer.report.pack"]._schedule(sub, self.start, self.end)
        with patch.object(
            type(self.env["ir.actions.report"]),
            "_render_qweb_pdf",
            return_value=(b"%PDF-test", "pdf"),
        ):
            pack._deliver()
        self.assertEqual(pack.state, "done")
        self.assertEqual(
            pack.mis_instance_ids.earlydryer_report_branch_ids, self.branch_1
        )
        with self.assertRaises(AccessError):
            pack.mis_instance_ids.with_user(self.user_manager_2).read(["name"])

    def test_home_action_only_when_unset(self):
        from ..hooks import post_init_hook

        previous = self.env.ref("earlydryer_reporting.action_job")
        self.user_management.action_id = previous.id
        new_owner = self._new_user(
            "report_new_owner", "earlydryer_base.group_management"
        )
        post_init_hook(self.env)
        self.assertEqual(self.user_management.action_id.id, previous.id)
        self.assertEqual(
            new_owner.action_id.id,
            self.env.ref("earlydryer_reporting.action_dashboard").id,
        )

    def test_daily_subscriber_reuses_eod_email_once(self):
        sub = self.subscription(frequency="daily", user=self.user_manager)
        partner = self.user_manager.partner_id
        partner.email = "report-daily@example.test"
        self.branch_1.eod_email_recipient_ids = partner
        report = self.env["earlydryer.notify.eod.report"].create(
            {"branch_id": self.branch_1.id, "date": self.stamp.date()}
        )
        with patch.object(
            type(self.env["ir.actions.report"]),
            "_render_qweb_pdf",
            return_value=(b"%PDF-test", "pdf"),
        ):
            report._deliver()
            report._deliver()
        mails = self.env["mail.mail"].search([("email_to", "=", partner.email)])
        self.assertEqual(len(mails), 1)
        self.assertIn("Performance indicators", mails.body_html)
        self.assertIn("Orders taken", mails.body_html)
        self.assertEqual(mails.attachment_ids, report.attachment_id)
        self.assertEqual(mails.state, "outgoing")
        self.assertEqual(sub.last_sent_on, self.stamp.date())
