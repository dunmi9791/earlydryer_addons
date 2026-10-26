# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import TransactionCase, tagged

from odoo.addons.earlydryer_tagging.models.earlydryer_tag_code import (
    format_printed,
    luhn_check_digit,
    luhn_is_valid,
    parse_printed,
)

# Same vectors as static/tests/unit/tag_code.test.js (the browser port)
VECTORS = [
    ("P1", 1, True, "P100000018"),
    ("TP1", 1234567, True, "TP112345674"),
    ("P1", 42, False, "P10000042"),
    ("ED2", 9999999, True, "ED299999997"),
    ("P2", 500, True, "P200005009"),
]


@tagged("post_install", "-at_install")
class TestTagCodeVectors(TransactionCase):
    def test_luhn(self):
        self.assertEqual(luhn_check_digit("7992739871"), 3)
        self.assertTrue(luhn_is_valid("79927398713"))
        self.assertFalse(luhn_is_valid("79927398710"))

    def test_vectors(self):
        for prefix, number, check_digit, code in VECTORS:
            self.assertEqual(format_printed(prefix, number, check_digit), code)
            self.assertEqual(parse_printed(code, prefix, check_digit), (number, True))
        self.assertIsNone(parse_printed("P10000001X", "P1"))
        self.assertEqual(parse_printed("P100000017", "P1"), (1, False))
