# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import hmac
import json

from odoo import http
from odoo.http import request


class NotificationWebhook(http.Controller):
    @http.route(
        "/earlydryer/notify/webhook/<int:provider_id>/<string:token>",
        type="http",
        auth="public",
        csrf=False,
        methods=["GET", "POST"],
        save_session=False,
    )
    def webhook(self, provider_id, token, **kwargs):
        # Narrow elevation for authentication only. Public users never gain model access.
        provider = (
            request.env["earlydryer.notify.provider"]
            .sudo()
            .browse(provider_id)
            .exists()
        )
        if (
            not provider
            or not provider.active
            or not hmac.compare_digest(provider.path_token or "", token)
        ):
            return request.make_response("Not found", status=404)
        if request.httprequest.method == "GET":
            args = request.httprequest.args
            if (
                args.get("hub.mode") == "subscribe"
                and provider.webhook_verify_token
                and hmac.compare_digest(
                    args.get("hub.verify_token", ""), provider.webhook_verify_token
                )
            ):
                return request.make_response(
                    args.get("hub.challenge", ""),
                    headers=[("Content-Type", "text/plain")],
                )
            return request.make_response("Forbidden", status=403)
        raw = request.httprequest.get_data(cache=True)
        if len(raw) > 1024 * 1024:
            return request.make_response("Too large", status=413)
        from ..providers.adapters import HttpAdapter

        if not HttpAdapter(provider).verify_webhook(
            (raw, request.httprequest.headers.get("X-Hub-Signature-256", ""))
        ):
            return request.make_response("Forbidden", status=403)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            return request.make_response("Invalid JSON", status=400)
        service = request.env.ref("earlydryer_notifications.user_notify_service")
        log = (
            request.env["earlydryer.notify.webhook.log"]
            .with_user(service)
            .create({"provider_id": provider.id, "payload": raw.decode("utf-8")})
        )
        log.with_delay(
            channel="root.earlydryer_notify", identity_key=f"webhook:{log.id}"
        )._process()
        return request.make_response("OK", status=200)
