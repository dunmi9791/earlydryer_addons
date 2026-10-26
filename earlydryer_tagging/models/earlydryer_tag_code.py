# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import re

from odoo import api, models

# printed tags: <prefix><7-digit number><check digit>
NUMBER_DIGITS = 7
MAX_NUMBER = 10**NUMBER_DIGITS - 1
# shape of a printed code with check digit, prefix unknown
PRINTED_RE = re.compile(rf"^([A-Z0-9]+?)(\d{{{NUMBER_DIGITS + 1}}})$")
DEFAULT_PREPRINTED_PATTERN = r"^[A-Z0-9]{4,16}$"


def luhn_check_digit(digits):
    """Mod-10 (Luhn) check digit of the string of ``digits``."""
    total = 0
    # from the right, every other digit (starting with the last one) is doubled
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 0:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return (10 - total % 10) % 10


def luhn_is_valid(digits):
    """Whether the last digit of ``digits`` is the Luhn check digit of the rest."""
    if len(digits) < 2 or not digits.isdigit():
        return False
    return luhn_check_digit(digits[:-1]) == int(digits[-1])


def normalize_code(code):
    """Scanned or typed code, upper-case, without blanks around it."""
    return (code or "").strip().upper()


def format_printed(prefix, number, check_digit=True):
    body = str(number).zfill(NUMBER_DIGITS)
    return f"{prefix}{body}{luhn_check_digit(body)}" if check_digit else prefix + body


def parse_printed(code, prefix, check_digit=True):
    """``(number, valid)`` of ``code`` read as a printed tag of ``prefix``,
    or None when it does not have that shape. ``valid`` is the check digit."""
    code = normalize_code(code)
    tail = code[len(prefix) :]
    length = NUMBER_DIGITS + (1 if check_digit else 0)
    if not code.startswith(prefix) or len(tail) != length or not tail.isdigit():
        return None
    valid = luhn_is_valid(tail) if check_digit else True
    return int(tail[:NUMBER_DIGITS]), valid


class EarlydryerTagCode(models.AbstractModel):
    """Generate and validate garment tag codes.

    Printed tags are ``<prefix><7-digit number><check digit>``, e.g.
    ``P100001230``: the prefix tells the plant, the Luhn check digit rejects
    a mistyped or misread code before any lookup. No separator, so Code128
    stays short. The prefixes come from a cached map, so validating a code
    never queries the database.
    """

    _name = "earlydryer.tag.code"
    _description = "Earlydryer Tag Code Helper"

    @api.model
    def normalize(self, code):
        return normalize_code(code)

    @api.model
    def generate(self, branch):
        """Next printed tag code of ``branch`` (from its tag sequence)."""
        return self._generate_many(branch, 1)[0]

    @api.model
    def _generate_many(self, branch, count):
        branch.ensure_one()
        first = branch._earlydryer_tag_take_numbers(count)
        return [self.format_number(branch, first + i) for i in range(count)]

    @api.model
    def format_number(self, branch, number):
        branch.ensure_one()
        return format_printed(branch.tag_prefix, number, branch.tag_check_digit)

    @api.model
    def parse(self, code):
        """Read ``code`` as a printed tag of a plant in printed mode.

        :returns: ``{"branch_id", "tag_mode", "number", "valid"}`` or None
            when no printed plant's prefix starts the code with a printed-tag
            tail. ``valid`` is False when the check digit is wrong.
        """
        code = normalize_code(code)
        prefixes = self.env["earlydryer.branch"]._earlydryer_tag_prefix_map()
        # longest prefix first: P1 and P12 may both exist
        for prefix in sorted(prefixes, key=len, reverse=True):
            branch_id, tag_mode, check_digit = prefixes[prefix]
            if tag_mode != "printed":
                continue
            parsed = parse_printed(code, prefix, check_digit)
            if parsed:
                return {
                    "branch_id": branch_id,
                    "tag_mode": tag_mode,
                    "number": parsed[0],
                    "valid": parsed[1],
                }
        return None

    @api.model
    def is_valid(self, code, branch=None):
        """Printed tag with a correct check digit (of ``branch`` if given).

        A code whose prefix is no plant's is checked on its shape only
        (7 digits and a Luhn digit at the end).
        """
        code = normalize_code(code)
        if branch:
            branch.ensure_one()
            parsed = parse_printed(
                code, branch.tag_prefix or "", branch.tag_check_digit
            )
            return bool(parsed and branch.tag_prefix and parsed[1])
        info = self.parse(code)
        if info:
            return info["valid"]
        match = PRINTED_RE.match(code)
        return bool(match) and luhn_is_valid(match.group(2))

    @api.model
    def branch_for(self, code):
        """Plant whose prefix starts the printed ``code`` (empty if none)."""
        info = self.parse(code)
        return self.env["earlydryer.branch"].browse(info["branch_id"] if info else [])

    @api.model
    def number_for(self, code, branch):
        """Tag number of the printed ``code`` of ``branch``, or None."""
        branch.ensure_one()
        parsed = parse_printed(code, branch.tag_prefix or "", branch.tag_check_digit)
        return parsed[0] if parsed and parsed[1] else None

    @api.model
    def is_valid_preprinted(self, code, branch):
        branch.ensure_one()
        pattern = branch.tag_preprinted_pattern or DEFAULT_PREPRINTED_PATTERN
        try:
            return bool(re.match(pattern, normalize_code(code)))
        except re.error:
            return False

    @api.model
    def is_valid_for_branch(self, code, branch):
        """Valid code for ``branch`` in its tag mode."""
        branch.ensure_one()
        if branch.tag_mode == "preprinted":
            return self.is_valid_preprinted(code, branch)
        return self.is_valid(code, branch)
