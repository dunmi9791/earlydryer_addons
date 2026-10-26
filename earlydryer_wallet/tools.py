# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

"""Nigerian phone numbers, as the till normalises them (earlydryer_pos)."""


def normalize_ng_phone(phone):
    """``0803 123 4567``, ``803...``, ``234803...`` → ``+2348031234567``.

    Other numbers keep their digits with a leading ``+`` when they had one.
    Returns ``""`` when there are no digits.
    """
    raw = (phone or "").strip()
    digits = "".join(char for char in raw if char.isdigit())
    if not digits:
        return ""
    if digits.startswith("234") and len(digits) == 13:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"+234{digits[1:]}"
    if len(digits) == 10 and digits[0] in "789":
        return f"+234{digits}"
    return f"+{digits}" if raw.startswith("+") else digits
