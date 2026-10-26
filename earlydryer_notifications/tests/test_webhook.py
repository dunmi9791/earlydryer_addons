# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestWebhook(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env["earlydryer.notify.provider"].create(
            {
                "name": "HTTP test",
                "channel": "whatsapp",
                "provider_type": "log_only",
                "app_secret": "test-secret",
                "webhook_verify_token": "verify-test",
            }
        )
        cls.route = (
            f"/earlydryer/notify/webhook/{cls.provider.id}/{cls.provider.path_token}"
        )

    def test_get_verification(self):
        result = self.url_open(
            self.route
            + "?hub.mode=subscribe&hub.verify_token=verify-test&hub.challenge=12345"
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.text, "12345")

    def test_bad_token(self):
        result = self.url_open(self.route + "wrong")
        self.assertEqual(result.status_code, 404)

    def test_bad_signature(self):
        result = self.url_open(
            self.route,
            data='{"entry":[]}',
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=wrong",
            },
        )
        self.assertEqual(result.status_code, 403)

    def test_signed_payload_queued(self):
        payload = json.dumps({"entry": []}).encode()
        signature = (
            "sha256=" + hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()
        )
        result = self.url_open(
            self.route,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
        )
        self.assertEqual(result.status_code, 200)
        log = self.env["earlydryer.notify.webhook.log"].search(
            [("provider_id", "=", self.provider.id)]
        )
        self.assertEqual(len(log), 1)
        self.assertFalse(log.processed)
        job = self.env["queue.job"].search(
            [
                ("model_name", "=", "earlydryer.notify.webhook.log"),
                ("method_name", "=", "_process"),
            ]
        )
        self.assertTrue(job)
