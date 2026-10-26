# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from dataclasses import dataclass


@dataclass
class SendResult:
    ok: bool
    external_id: str = ""
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    cost: float = 0.0


@dataclass
class WebhookEvent:
    kind: str
    external_id: str
    phone: str = ""
    body: str = ""
    state: str = ""
    media: str = ""
    error_code: str = ""
    received_on: str = ""


class BaseNotifyAdapter:
    def __init__(self, provider):
        self.provider = provider

    def send_template(self, message):
        raise NotImplementedError

    def send_text(self, message):
        raise NotImplementedError

    def verify_webhook(self, request):
        raise NotImplementedError

    def parse_webhook(self, payload, headers):
        raise NotImplementedError
