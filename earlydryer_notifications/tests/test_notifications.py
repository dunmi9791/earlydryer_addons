# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.addons.earlydryer_laundry_order.tests.common import LaundryJobCommon
from odoo.addons.queue_job.tests.common import trap_jobs
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..providers import SendResult, WebhookEvent
from ..providers.adapters import GenericHttpAdapter, LogOnlyAdapter, MetaAdapter
from ..tools import phone_e164, quiet_eta, sms_size


@tagged("post_install", "-at_install")
class TestNotifications(LaundryJobCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Messages = cls.env["earlydryer.notify.message"]
        cls.Inbound = cls.env["earlydryer.notify.inbound"]
        cls.Provider = cls.env["earlydryer.notify.provider"]
        cls.Provider.search([("active", "=", True)]).active = False
        cls.wa = cls.Provider.create(
            {
                "name": "WA test",
                "channel": "whatsapp",
                "provider_type": "log_only",
                "app_secret": "test-only",
                "webhook_verify_token": "test-verify",
            }
        )
        cls.sms = cls.Provider.create(
            {"name": "SMS test", "channel": "sms", "provider_type": "log_only"}
        )
        cls.cs = cls._new_user(
            "notify_cs", "earlydryer_base.group_customer_service", cls.branch_1
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "earlydryer_notify.quiet_start", 0
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "earlydryer_notify.quiet_end", 0
        )

    def setUp(self):
        super().setUp()
        self.trap = self.enterContext(trap_jobs())

    def _message(self, code="job_received", job=None, **kwargs):
        job = job or self._create_job()
        messages = self.Messages.search(
            [
                ("res_model", "=", "laundry.job"),
                ("res_id", "=", job.id),
                ("event_id.code", "=", code),
            ]
        )
        return messages[:1] or self.Messages.notify(code, job, **kwargs)

    def _inbound(self, body, number=None, external=None, provider=None):
        return self.Inbound._receive(
            provider or self.wa,
            WebhookEvent(
                "inbound",
                external or f"in-{len(self.Inbound.search([]))}",
                phone=number or self.partner.phone,
                body=body,
            ),
        )

    def _ready(self, fulfilment="collect"):
        job = self._create_job(fulfilment=fulfilment)
        self._walk(job, [*self.PRODUCTION_PATH, "qc_pass", "packed"])
        job.shelf_id = self.branch_1.shelf_ids[:1]
        job.action_move_to("ready", employee=self.employee)
        return job

    def test_received_rendered_and_queued(self):
        job = self._create_job()
        message = self._message(job=job)
        self.assertEqual(message.state, "queued")
        self.assertIn(job.name, message.body)
        self.assertIn(str(job.item_count), message.body)
        self.assertTrue(json.loads(message.params_json))
        self.assertEqual(message.provider_id, self.wa)
        self.assertGreater(self.trap.jobs_count(), 0)

    def test_ready_has_shelf_and_chatter(self):
        job = self._ready()
        message = self._message("job_ready", job)
        self.assertIn(job.shelf_id.name, message.body)
        message._send()
        self.assertEqual(message.state, "sent")
        self.assertTrue(
            job.message_ids.filtered(lambda m: "Customer message" in str(m.body))
        )

    def test_delivery_hooks(self):
        job = self._ready("deliver")
        job.with_user(self.user_manager).action_out_for_delivery()
        self.assertTrue(self._message("job_out_for_delivery", job))
        job.with_user(self.user_front_desk).action_delivered()
        self.assertTrue(self._message("job_delivered", job))

    def test_reminder_occurrences(self):
        job = self._create_job()
        job._earlydryer_send_uncollected_reminder(7)
        job._earlydryer_send_uncollected_reminder(7)
        job._earlydryer_send_uncollected_reminder(10)
        messages = self.Messages.search(
            [("res_id", "=", job.id), ("event_id.code", "=", "uncollected_reminder")]
        )
        self.assertEqual(len(messages), 2)
        self.assertTrue(any("7 days" in m.body for m in messages))

    def test_broken_template_never_breaks_stage(self):
        template = self.env.ref("earlydryer_notifications.template_job_ready_whatsapp")
        template.body = "{{ object.this_field_does_not_exist }}"
        job = self._ready()
        self.assertEqual(job.state, "ready")
        message = self._message("job_ready", job)
        self.assertEqual(message.state, "failed")
        self.assertTrue(message.activity_ids)

    def test_provider_exception_is_recorded(self):
        message = self._message()
        with patch.object(
            LogOnlyAdapter,
            "send_template",
            side_effect=RuntimeError("secret must not leak"),
        ):
            message._send()
        self.assertEqual(message.state, "queued")
        self.assertEqual(message.attempts, 1)
        self.assertNotIn("secret", message.error_message)

    def test_partner_sms_preference(self):
        self.partner.earlydryer_notify_channel = "sms"
        self.assertEqual(self._message().channel, "sms")

    def test_whatsapp_unavailable_skips_wa(self):
        self.partner.earlydryer_whatsapp_unavailable = True
        self.assertEqual(self._message().channel, "sms")

    def test_no_phone_no_message(self):
        self.partner.phone = False
        job = self._create_job()
        self.assertFalse(self.Messages.notify("job_ready", job))

    def test_optout_no_message(self):
        self.partner.earlydryer_notify_opt_in = False
        job = self._create_job()
        self.assertFalse(self.Messages.notify("job_ready", job))

    def test_optout_after_enqueue_cancels(self):
        message = self._message()
        self.partner.earlydryer_notify_opt_in = False
        message._send()
        self.assertEqual(message.state, "cancelled")

    def test_inactive_and_wrong_plant(self):
        event = self.env.ref("earlydryer_notifications.event_job_ready")
        event.branch_ids = self.branch_2
        self.assertFalse(self.Messages.notify("job_ready", self._create_job()))
        event.write({"branch_ids": [(5, 0, 0)], "active": False})
        self.assertFalse(self.Messages.notify("job_ready", self._create_job()))

    def test_permanent_fallback(self):
        message = self._message()
        with patch.object(
            LogOnlyAdapter,
            "send_template",
            return_value=SendResult(False, error_code="not_on_whatsapp"),
        ):
            message._send()
        self.assertEqual(message.state, "failed")
        self.assertTrue(self.partner.earlydryer_whatsapp_unavailable)
        self.assertEqual(message.fallback_id.channel, "sms")
        self.assertEqual(message.fallback_id.fallback_of_id, message)
        message._send()
        self.assertEqual(len(message.fallback_id), 1)

    def test_optout_provider_has_no_fallback(self):
        message = self._message()
        with patch.object(
            LogOnlyAdapter,
            "send_template",
            return_value=SendResult(False, error_code="opted_out"),
        ):
            message._send()
        self.assertTrue(self.partner.earlydryer_notify_opt_out)
        self.assertFalse(message.fallback_id)

    def test_retry_backoff_exhaustion(self):
        message = self._message()
        with patch.object(
            LogOnlyAdapter,
            "send_template",
            return_value=SendResult(False, error_code="429", retryable=True),
        ):
            for attempt in range(1, 6):
                message.eta = False
                message._send()
                self.assertEqual(message.attempts, attempt)
                if attempt < 5:
                    self.assertEqual(message.state, "queued")
                    expected = [1, 5, 15, 60][attempt - 1]
                    self.assertAlmostEqual(
                        (message.eta - fields.Datetime.now()).total_seconds(),
                        expected * 60,
                        delta=3,
                    )
        self.assertEqual(message.state, "failed")
        self.assertFalse(message.fallback_id)

    def test_database_rate_limit(self):
        self.wa.rate_limit_per_minute = 1
        first = self._message()
        second = self._message(job=self._create_job())
        first._send()
        second._send()
        self.assertEqual(first.state, "sent")
        self.assertEqual(second.attempts, 0)
        self.assertTrue(second.eta)

    def test_duplicate_send_is_noop(self):
        message = self._message()
        message._send()
        message._send()
        self.assertEqual(message.attempts, 1)

    def test_quiet_hours_lagos(self):
        self.assertEqual(quiet_eta(datetime(2026, 10, 1, 21)), datetime(2026, 10, 2, 6))
        self.assertIsNone(quiet_eta(datetime(2026, 10, 1, 10)))
        self.assertEqual(quiet_eta(datetime(2026, 10, 1, 3)), datetime(2026, 10, 1, 6))

    def test_nonurgent_held_urgent_not_held(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "earlydryer_notify.quiet_start", 21
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "earlydryer_notify.quiet_end", 7
        )
        job = self._create_job()
        with patch(
            "odoo.addons.earlydryer_notifications.models.notify_message.fields.Datetime.now",
            return_value=datetime(2026, 10, 1, 21),
        ):
            held = self.Messages.notify("job_ready", job)
            urgent = self.Messages.notify("job_out_for_delivery", job)
        self.assertEqual(held.state, "held")
        self.assertEqual(held.eta, datetime(2026, 10, 2, 6))
        self.assertEqual(urgent.state, "queued")

    def test_dedupe_and_real_repeat(self):
        job = self._create_job()
        event = self.env.ref("earlydryer_notifications.event_job_ready")
        first = self.Messages.notify(event.code, job, context={"occurrence": "one"})
        self.assertEqual(
            first, self.Messages.notify(event.code, job, context={"occurrence": "two"})
        )
        event.allow_repeat = True
        second = self.Messages.notify(event.code, job, context={"occurrence": "two"})
        self.assertNotEqual(first, second)
        self.assertEqual(
            second, self.Messages.notify(event.code, job, context={"occurrence": "two"})
        )

    def test_stop_and_start(self):
        stop = self._inbound(" STOP ")
        self.assertTrue(self.partner.earlydryer_notify_opt_out)
        self.assertEqual(stop.state, "auto_replied")
        confirmation = self.Messages.search([("inbound_id", "=", stop.id)])
        confirmation._send()
        self.assertEqual(confirmation.state, "sent")
        self._inbound("START", external="start-1")
        self.assertFalse(self.partner.earlydryer_notify_opt_out)

    def test_sms_stop(self):
        self._inbound("STOP", provider=self.sms)
        self.assertTrue(self.partner.earlydryer_notify_opt_out)

    def test_status_privacy(self):
        job = self._create_job()
        other = self.env["res.partner"].create(
            {"name": "Other", "phone": "08031111111"}
        )
        foreign = self._create_job(partner=other)
        inbound = self._inbound("status")
        reply = self.Messages.search([("inbound_id", "=", inbound.id)])
        self.assertIn(job.name, reply.body)
        self.assertNotIn(foreign.name, reply.body)
        unknown = self._inbound(foreign.name, external="foreign-job")
        self.assertEqual(unknown.state, "needs_reply")
        self.assertNotIn(
            foreign.name, self.Messages.search([("inbound_id", "=", unknown.id)]).body
        )

    def test_invalid_tag_is_not_queried(self):
        self._create_job()
        with patch.object(
            type(self.env["earlydryer.tag.code"]), "is_valid", return_value=False
        ):
            inbound = self._inbound("P100000012")
        self.assertEqual(inbound.state, "needs_reply")

    def test_unknown_ack_throttled_and_activity(self):
        self._create_job()
        first = self._inbound("Can you help?")
        second = self._inbound("Please?", external="ack-2")
        self.assertTrue(first.activity_ids)
        self.assertEqual(first.state, "needs_reply")
        self.assertEqual(
            len(self.Messages.search([("inbound_id", "in", (first | second).ids)])), 1
        )

    def test_duplicate_inbound_ignored(self):
        first = self._inbound("status", external="duplicate")
        second = self._inbound("status", external="duplicate")
        self.assertEqual(first, second)

    def test_balance_bot(self):
        self._create_job()
        inbound = self._inbound("balance")
        self.assertEqual(inbound.state, "auto_replied")
        self.assertIn(
            "Wallet balance",
            self.Messages.search([("inbound_id", "=", inbound.id)]).body,
        )

    def test_reply_window_and_server_enforcement(self):
        inbound = self._inbound("question")
        inbound.received_on = fields.Datetime.now() - timedelta(hours=25)
        self.partner.earlydryer_last_inbound_on = inbound.received_on
        with self.assertRaises(UserError):
            inbound._reply("late")
        template = self.env.ref("earlydryer_notifications.template_job_ready_whatsapp")
        template.approved = True
        message = inbound._reply("", template)
        self.assertFalse(message.free_text)
        inbound.received_on = fields.Datetime.now()
        free = inbound._reply("Hello")
        inbound.received_on = fields.Datetime.now() - timedelta(hours=25)
        self.partner.earlydryer_last_inbound_on = inbound.received_on
        free._send()
        self.assertEqual(free.error_code, "window_expired")

    def test_frontdesk_cannot_reply(self):
        inbound = self._inbound("question")
        with self.assertRaises(AccessError):
            inbound.with_user(self.user_front_desk).action_reply()

    def test_provider_secrets_denied(self):
        with self.assertRaises(AccessError):
            self.wa.with_user(self.cs).read(["api_token"])

    def test_other_plant_hidden(self):
        first = self._message()
        second = self._message(job=self._create_job(branch=self.branch_2))
        visible = self.Messages.with_user(self.cs).search(
            [("id", "in", (first | second).ids)]
        )
        self.assertEqual(visible.ids, first.ids)

    def test_retention_preserves_metadata(self):
        message = self._message()
        self.env.cr.execute(
            "UPDATE earlydryer_notify_message SET create_date=%s WHERE id=%s",
            [fields.Datetime.now() - timedelta(days=400), message.id],
        )
        self.Messages._cron_retention()
        self.assertFalse(message.body)
        self.assertTrue(message.phone)
        self.assertTrue(message.event_id)

    def test_template_cannot_read_secrets(self):
        template = self.env.ref("earlydryer_notifications.template_job_ready_whatsapp")
        template.body = (
            "{{ object.env['earlydryer.notify.provider'].sudo().search([]).api_token }}"
        )
        message = self.Messages.notify("job_ready", self._create_job())
        self.assertFalse(message)
        self.assertTrue(self.Messages.search([("error_code", "=", "configuration")]))

    def test_sms_segment_counter(self):
        self.assertEqual(sms_size("a" * 161), (161, 2))
        self.assertEqual(sms_size("₦" * 71), (71, 2))
        self.assertEqual(phone_e164("0803 123 4567"), "+2348031234567")
        self.assertFalse(phone_e164("123"))

    def test_meta_payload_and_errors(self):
        message = self._message()
        provider = SimpleNamespace(
            graph_version="v23.0", phone_number_id="123", api_token="unit-token"
        )
        adapter = MetaAdapter(provider)
        with patch("requests.request") as request:
            request.return_value.status_code = 200
            request.return_value.json.return_value = {"messages": [{"id": "wamid.1"}]}
            result = adapter.send_template(message)
            payload = request.call_args.kwargs["json"]
            self.assertEqual(payload["type"], "template")
            self.assertEqual(
                payload["template"]["components"][0]["parameters"][0]["type"], "text"
            )
            self.assertEqual(result.external_id, "wamid.1")
            request.return_value.status_code = 429
            request.return_value.json.return_value = {"error": {"code": 130429}}
            self.assertTrue(adapter.send_template(message).retryable)
            request.return_value.status_code = 400
            request.return_value.json.return_value = {"error": {"code": 132001}}
            self.assertFalse(adapter.send_template(message).retryable)

    def test_generic_safe_substitution_and_paths(self):
        provider = SimpleNamespace(
            api_token="token",
            sender_id="Earlydryer",
            body_template='{"to":"{to}","message":"{text}"}',
            headers_json="{}",
            url_template="https://example.invalid/send",
            body_encoding="json",
            http_method="POST",
            success_json_path="data.ok",
            message_id_json_path="data.id",
            error_json_path="error.code",
            cost_json_path="data.cost",
        )
        message = SimpleNamespace(
            phone="+2348031234567",
            body='Hello "friend"\\nNew line',
            meta_template_name="",
            params_json="[]",
        )
        with patch("requests.request") as request:
            request.return_value.status_code = 200
            request.return_value.json.return_value = {
                "data": {"ok": True, "id": "sms-1", "cost": 2.5}
            }
            result = GenericHttpAdapter(provider).send_text(message)
            self.assertTrue(result.ok)
            self.assertEqual(result.cost, 2.5)
            self.assertEqual(request.call_args.kwargs["json"]["message"], message.body)
            self.assertEqual(request.call_args.kwargs["timeout"], 10)

    def test_status_callbacks_forward_only(self):
        message = self._message()
        message._send()

        def callback(state):
            payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "statuses": [
                                        {"id": message.external_id, "status": state}
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
            log = self.env["earlydryer.notify.webhook.log"].create(
                {"provider_id": self.wa.id, "payload": json.dumps(payload)}
            )
            log._process()

        callback("read")
        callback("delivered")
        callback("failed")
        self.assertEqual(message.state, "read")

    def test_failed_callback_falls_back(self):
        message = self._message()
        message._send()
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": message.external_id,
                                        "status": "failed",
                                        "errors": [{"code": 131026}],
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        log = self.env["earlydryer.notify.webhook.log"].create(
            {"provider_id": self.wa.id, "payload": json.dumps(payload)}
        )
        log._process()
        self.assertEqual(message.state, "failed")
        self.assertTrue(message.fallback_id)

    def test_alert_threshold_and_branch_recipients(self):
        rule = self.env.ref("earlydryer_notifications.rule_alert_large_discount")
        rule.write(
            {
                "recipient_user_ids": [
                    (6, 0, [self.user_manager.id, self.user_front_desk_2.id])
                ],
                "recipient_group_ids": [(5, 0, 0)],
            }
        )
        job = self._create_job()
        self.Messages.notify(
            "alert_large_discount", job, context={"value": 5, "occurrence": "low"}
        )
        self.assertFalse(
            self.env["earlydryer.notify.alert"].search([("rule_id", "=", rule.id)])
        )
        self.Messages.notify(
            "alert_large_discount", job, context={"value": 15, "occurrence": "high"}
        )
        alert = self.env["earlydryer.notify.alert"].search([("rule_id", "=", rule.id)])
        self.assertEqual(len(alert), 1)
        self.assertEqual(rule._recipients(self.branch_1), self.user_manager)
        alert._deliver()
        self.assertTrue(
            job.activity_ids.filtered(lambda a: a.user_id == self.user_manager)
        )

    def test_overdue_digest_due_once(self):
        job = self._create_job()
        job.promised_on = fields.Datetime.now() - timedelta(hours=5)
        rule = self.env.ref("earlydryer_notifications.rule_alert_overdue")
        rule.write({"branch_ids": [(6, 0, self.branch_1.ids)], "digest_times": "00:00"})
        self.env["earlydryer.notify.alert.rule"]._cron_digest()
        alerts = self.env["earlydryer.notify.alert"].search([("rule_id", "=", rule.id)])
        self.assertEqual(len(alerts), 1)
        self.assertIn(job.name, alerts.context_json)
        self.env["earlydryer.notify.alert.rule"]._cron_digest()
        self.assertEqual(
            self.env["earlydryer.notify.alert"].search_count(
                [("rule_id", "=", rule.id)]
            ),
            1,
        )

    def test_empty_overdue_digest_not_sent(self):
        rule = self.env.ref("earlydryer_notifications.rule_alert_overdue")
        rule.write({"branch_ids": [(6, 0, self.branch_1.ids)], "digest_times": "00:00"})
        self.env["earlydryer.notify.alert.rule"]._cron_digest()
        self.assertFalse(
            self.env["earlydryer.notify.alert"].search([("rule_id", "=", rule.id)])
        )

    def test_eod_once_and_resend(self):
        self.branch_1.eod_report_time = 0
        reports = self.env["earlydryer.notify.eod.report"]
        self.Branch._cron_eod()
        self.Branch._cron_eod()
        scheduled = reports.search([("branch_id", "=", self.branch_1.id)])
        self.assertEqual(len(scheduled), 1)
        scheduled._deliver()
        self.assertEqual(scheduled.state, "done")
        self.assertEqual(self.branch_1.eod_last_sent_on, scheduled.date)
        wizard = self.env["earlydryer.notify.eod.wizard"].create(
            {"branch_id": self.branch_1.id, "date": scheduled.date}
        )
        wizard.action_send()
        self.assertEqual(
            reports.search_count([("branch_id", "=", self.branch_1.id)]), 2
        )

    def test_eod_figures_and_pending_jobs(self):
        job = self._create_job()
        figures = self.branch_1._earlydryer_eod_figures(fields.Date.today())
        self.assertEqual(figures["orders"], 1)
        self.assertEqual(figures["sales_value"], job.amount_total)
        self.assertEqual(figures["wallet_topups"], 0)
        self.assertEqual(figures["payments"], {})

    def test_unknown_stop_is_kept_when_contact_created_later(self):
        number = "+2348039999999"
        inbound = self._inbound("STOP", number=number, external="unknown-stop")
        self.assertEqual(inbound.state, "auto_replied")
        partner = self.env["res.partner"].create(
            {"name": "Later contact", "phone": number}
        )
        job = self._create_job(partner=partner)
        self.assertFalse(self.Messages.notify("job_ready", job))
        self._inbound("START", number=number, external="unknown-start")
        self.assertTrue(self.Messages.notify("job_ready", job))

    def test_cs_cannot_change_inbound_identity(self):
        inbound = self._inbound("question")
        with self.assertRaises(AccessError):
            inbound.with_user(self.cs).write({"phone": "+2348031111111"})
        inbound.with_user(self.cs).action_assign_to_me()
        self.assertEqual(inbound.assigned_user_id, self.cs)

    def test_branch_manager_can_change_only_own_eod_settings(self):
        self.branch_1.with_user(self.user_manager).write({"eod_report_time": 19.5})
        self.assertEqual(self.branch_1.eod_report_time, 19.5)
        with self.assertRaises(AccessError):
            self.branch_2.with_user(self.user_front_desk).write({"eod_report_time": 19})

    def test_eod_email_queues_pdf_attachment(self):
        self.partner.email = "unit@example.invalid"
        self.branch_1.eod_email_recipient_ids = self.partner
        report = self.env["earlydryer.notify.eod.report"]._schedule(
            self.branch_1, fields.Date.today()
        )
        with patch.object(
            type(self.env["ir.actions.report"]),
            "_render_qweb_pdf",
            return_value=(b"%PDF-unit-test", "pdf"),
        ):
            report._deliver()
        self.assertTrue(report.attachment_id)
        mail = self.env["mail.mail"].search(
            [("attachment_ids", "in", report.attachment_id.ids)]
        )
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.state, "outgoing")

    def test_logonly_synchronous_queue_helper(self):
        message = self._message()
        self.trap.perform_enqueued_jobs()
        self.assertEqual(message.state, "sent")

    def test_staff_rule_sms_only_and_employee_mobile(self):
        self.user_manager.partner_id.write(
            {"phone": False, "earlydryer_notify_opt_in": True}
        )
        self.env["hr.employee"].create(
            {
                "name": "Notification manager",
                "user_id": self.user_manager.id,
                "earlydryer_branch_id": self.branch_1.id,
                "mobile_phone": "+2348038888888",
            }
        )
        rule = self.env.ref("earlydryer_notifications.rule_alert_scan_mismatch")
        rule.write(
            {
                "channels": "sms",
                "recipient_user_ids": [(6, 0, self.user_manager.ids)],
                "recipient_group_ids": [(5, 0, 0)],
            }
        )
        job = self._create_job()
        self.Messages.notify(
            "alert_scan_mismatch", job, context={"occurrence": "sms-only"}
        )
        alert = self.env["earlydryer.notify.alert"].search([("rule_id", "=", rule.id)])
        alert._deliver()
        message = self.Messages.search([("event_id", "=", rule.event_id.id)])
        self.assertEqual(message.channel, "sms")
        self.assertEqual(message.phone, "+2348038888888")

    def test_optional_damage_hook(self):
        job = self._create_job()
        job._earlydryer_on_damage_found(SimpleNamespace(id=9191))
        self.assertTrue(
            self.env["earlydryer.notify.alert"].search(
                [
                    ("rule_id.event_id.code", "=", "alert_damage_found"),
                    ("res_model", "=", "laundry.job"),
                    ("res_id", "=", job.id),
                ]
            )
        )

    def test_scan_mismatch_hook(self):
        job = self._create_job()
        log = self.env["earlydryer.scan.log"].create(
            {
                "code": "WRONG",
                "mode": "pack",
                "result": "wrong_job",
                "job_id": job.id,
                "expected_job_id": job.id,
                "earlydryer_branch_id": self.branch_1.id,
            }
        )
        job._earlydryer_on_scan_mismatch(log)
        self.assertTrue(
            self.env["earlydryer.notify.alert"].search(
                [
                    ("rule_id.event_id.code", "=", "alert_scan_mismatch"),
                    ("res_model", "=", log._name),
                    ("res_id", "=", log.id),
                ]
            )
        )

    def test_extra_staff_phone_is_scoped_to_plant(self):
        self.user_front_desk_2.partner_id.write(
            {"phone": "+2348037777777", "earlydryer_notify_opt_in": True}
        )
        rule = self.env.ref("earlydryer_notifications.rule_alert_scan_mismatch")
        rule.write(
            {
                "channels": "sms",
                "recipient_user_ids": [(5, 0, 0)],
                "recipient_group_ids": [(5, 0, 0)],
                "extra_phones": "+2348037777777",
            }
        )
        job = self._create_job()
        self.Messages.notify(
            "alert_scan_mismatch", job, context={"occurrence": "other-plant-phone"}
        )
        alert = self.env["earlydryer.notify.alert"].search([("rule_id", "=", rule.id)])
        alert._deliver()
        self.assertFalse(self.Messages.search([("event_id", "=", rule.event_id.id)]))
