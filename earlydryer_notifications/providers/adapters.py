# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

"""Plain adapters. Never include HTTP responses, URLs or credentials in errors."""

import hashlib
import hmac
import json
import uuid
from urllib.parse import quote

import requests

from .base import BaseNotifyAdapter, SendResult, WebhookEvent


def path(data, dotted):
    for part in (dotted or "").split("."):
        if not part:
            continue
        data = data.get(part) if isinstance(data, dict) else None
    return data


def substitute(value, values):
    if isinstance(value, dict):
        return {k: substitute(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, values) for v in value]
    if isinstance(value, str):
        for key, replacement in values.items():
            value = value.replace("{" + key + "}", str(replacement))
    return value


class LogOnlyAdapter(BaseNotifyAdapter):
    def send_template(self, message):
        return SendResult(True, "log-" + str(uuid.uuid4()))

    send_text = send_template

    def verify_webhook(self, request):
        return False  # development inbound uses the same HMAC as real providers

    def parse_webhook(self, payload, headers):
        return MetaAdapter(self.provider).parse_webhook(payload, headers)


class HttpAdapter(BaseNotifyAdapter):
    def _request(self, method, url, **kwargs):
        try:
            response = requests.request(
                method, url, timeout=10, allow_redirects=False, **kwargs
            )
            try:
                data = response.json()
            except ValueError:
                data = {}
            return response.status_code, data
        except requests.RequestException:
            return 0, {}

    def verify_webhook(self, request):
        raw, signature = request
        secret = self.provider.app_secret
        expected = (
            "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if secret
            else ""
        )
        return bool(expected and signature and hmac.compare_digest(expected, signature))


class MetaAdapter(HttpAdapter):
    def _send(self, payload):
        p = self.provider
        code, data = self._request(
            "POST",
            f"https://graph.facebook.com/{p.graph_version}/{p.phone_number_id}/messages",
            headers={"Authorization": "Bearer " + (p.api_token or "")},
            json=payload,
        )
        error = data.get("error", {})
        error_code = str(error.get("code", code))
        if 200 <= code < 300 and data.get("messages"):
            return SendResult(True, str(data["messages"][0]["id"]))
        retry = (
            code == 0
            or code == 429
            or code >= 500
            or error_code
            in {"4", "80007", "130429", "131000", "131016", "131048", "131056"}
        )
        return SendResult(
            False,
            error_code=error_code,
            error_message="WhatsApp request rejected"
            if code
            else "Provider network error",
            retryable=retry,
        )

    def send_template(self, message):
        payload = {
            "messaging_product": "whatsapp",
            "to": message.phone,
            "type": "template",
            "template": {
                "name": message.meta_template_name,
                "language": {"code": message.meta_language},
            },
        }
        params = json.loads(message.params_json or "[]")
        if params:
            payload["template"]["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(v)} for v in params],
                }
            ]
        return self._send(payload)

    def send_text(self, message):
        return self._send(
            {
                "messaging_product": "whatsapp",
                "to": message.phone,
                "type": "text",
                "text": {"body": message.body},
            }
        )

    def parse_webhook(self, payload, headers):
        events = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                # Do not accept callbacks belonging to another business number.
                if (
                    self.provider.phone_number_id
                    and value.get("metadata", {}).get("phone_number_id")
                    != self.provider.phone_number_id
                ):
                    continue
                for status in value.get("statuses", []):
                    errors = status.get("errors") or [{}]
                    events.append(
                        WebhookEvent(
                            "status",
                            str(status.get("id", "")),
                            state=status.get("status", ""),
                            error_code=str(errors[0].get("code", "")),
                        )
                    )
                for msg in value.get("messages", []):
                    media = (
                        msg.get(msg.get("type"), {})
                        if msg.get("type") != "text"
                        else {}
                    )
                    events.append(
                        WebhookEvent(
                            "inbound",
                            str(msg.get("id", "")),
                            phone=msg.get("from", ""),
                            body=msg.get("text", {}).get("body", ""),
                            media=str(media.get("id", "")),
                            received_on=msg.get("timestamp", ""),
                        )
                    )
        return events


class GenericHttpAdapter(HttpAdapter):
    def send_text(self, message):
        p = self.provider
        values = {
            "to": message.phone,
            "sender": p.sender_id or "",
            "text": message.body or "",
            "template": message.meta_template_name or "",
            "params_json": message.params_json or "[]",
            "api_token": p.api_token or "",
        }
        # JSON is decoded BEFORE interpolation, so quotes/newlines in messages are safe.
        body = substitute(json.loads(p.body_template or "{}"), values)
        headers = substitute(json.loads(p.headers_json or "{}"), values)
        url_values = {k: quote(str(v), safe="") for k, v in values.items()}
        url = substitute(p.url_template, url_values)
        kwargs = {
            "headers": headers,
            "json" if p.body_encoding == "json" else "data": body,
        }
        code, data = self._request(p.http_method, url, **kwargs)
        ok = 200 <= code < 300 and (
            not p.success_json_path or bool(path(data, p.success_json_path))
        )
        return SendResult(
            ok,
            str(path(data, p.message_id_json_path) or "") if ok else "",
            "" if ok else str(path(data, p.error_json_path) or code)[:80],
            "" if ok else "Gateway rejected message",
            code == 0 or code == 429 or code >= 500,
            float(path(data, p.cost_json_path) or 0) if p.cost_json_path else 0,
        )

    send_template = send_text

    def parse_webhook(self, payload, headers):
        # Canonical gateway contract; gateway must map its callbacks to these fields.
        return [
            WebhookEvent(
                kind=e.get("kind", "inbound"),
                external_id=str(e.get("external_id", "")),
                phone=e.get("phone", ""),
                body=e.get("body", ""),
                state=e.get("state", ""),
                media=e.get("media", ""),
                error_code=str(e.get("error_code", "")),
            )
            for e in payload.get("events", [])
        ]


def adapter_for(provider):
    return {
        "meta_cloud": MetaAdapter,
        "generic_http": GenericHttpAdapter,
        "log_only": LogOnlyAdapter,
    }[provider.provider_type](provider)
