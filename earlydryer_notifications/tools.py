# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

"""Shared formatting; Python phone normalization stays in earlydryer_wallet.tools."""

import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from odoo.addons.earlydryer_wallet.tools import normalize_ng_phone

LAGOS = ZoneInfo("Africa/Lagos")


def phone_e164(value):
    value = normalize_ng_phone(value)
    return value if re.fullmatch(r"\+[1-9][0-9]{7,14}", value or "") else ""


def quiet_eta(now, start=21.0, end=7.0):
    local = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(LAGOS)
    hour = local.hour + local.minute / 60
    quiet = (hour >= start or hour < end) if start > end else start <= hour < end
    if start == end or not quiet:
        return None
    target = local.replace(
        hour=int(end * 60) // 60, minute=int(end * 60) % 60, second=0, microsecond=0
    )
    if target <= local:
        target += timedelta(days=1)
    return target.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def sms_size(text):
    basic = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
    extension = "^{}\\[~]|€"
    gsm = all(c in basic + extension for c in text)
    count = (
        sum(2 if c in extension else 1 for c in text)
        if gsm
        else len(text.encode("utf-16-be")) // 2
    )
    single, multi = (160, 153) if gsm else (70, 67)
    return count, (
        1 if count <= single else (count + multi - 1) // multi
    ) if count else 0
