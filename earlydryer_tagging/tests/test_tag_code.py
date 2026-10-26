# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.earlydryer_tagging.models.earlydryer_tag_code import (
    luhn_check_digit,
    luhn_is_valid,
)

from .common import TaggingCommon


@tagged("post_install", "-at_install")
class TestTagCode(TaggingCommon):
    def test_luhn_reference_value(self):
        # the classic example of the Luhn algorithm
        self.assertEqual(luhn_check_digit("7992739871"), 3)
        self.assertTrue(luhn_is_valid("79927398713"))
        self.assertFalse(luhn_is_valid("79927398710"))

    def test_generate_prefix_padding_check_digit(self):
        self.assertEqual(self.branch_1.tag_prefix, "TP1")
        sequence = self.branch_1.tag_sequence_id
        self.assertEqual(sequence.implementation, "no_gap")
        self.assertEqual(sequence.padding, 7)
        first = self.branch_1._earlydryer_tag_next_number()
        code = self.TagCode.generate(self.branch_1)
        self.assertEqual(len(code), len("TP1") + 8)
        self.assertTrue(code.startswith("TP1"))
        self.assertEqual(code[3:10], str(first).zfill(7))
        self.assertTrue(luhn_is_valid(code[3:]))
        self.assertTrue(self.TagCode.is_valid(code))
        self.assertTrue(self.TagCode.is_valid(code, self.branch_1))
        self.assertFalse(self.TagCode.is_valid(code, self.branch_2))
        # consecutive numbers, one block
        codes = self.TagCode._generate_many(self.branch_1, 3)
        numbers = [int(c[3:10]) for c in codes]
        self.assertEqual(numbers, [first + 1, first + 2, first + 3])

    def test_is_valid_rejects_typos(self):
        code = self.TagCode.format_number(self.branch_1, 1234567)
        self.assertTrue(self.TagCode.is_valid(code))
        digits_start = len(self.branch_1.tag_prefix)
        for position in range(digits_start, len(code)):
            for digit in "0123456789":
                if digit == code[position]:
                    continue
                typo = code[:position] + digit + code[position + 1 :]
                self.assertFalse(self.TagCode.is_valid(typo), typo)
        swaps = 0
        for position in range(digits_start, len(code) - 1):
            a, b = code[position], code[position + 1]
            if a == b or {a, b} == {"0", "9"}:
                # the one transposition Luhn cannot see
                continue
            swapped = code[:position] + b + a + code[position + 2 :]
            self.assertFalse(self.TagCode.is_valid(swapped), swapped)
            swaps += 1
        self.assertGreater(swaps, 3)

    def test_branch_for(self):
        code = self.TagCode.generate(self.branch_1)
        self.assertEqual(self.TagCode.branch_for(code), self.branch_1)
        self.assertEqual(self.TagCode.branch_for(code.lower()), self.branch_1)
        self.assertFalse(self.TagCode.branch_for("ZZ900000017"))
        # pre-printed plants have no printed codes
        self.assertFalse(self.TagCode.branch_for("TP2" + code[3:]))

    def test_longest_prefix_wins(self):
        branch_12 = self.Branch.create({"name": "Test Plant 12", "code": "TP12"})
        code = self.TagCode.generate(branch_12)
        self.assertEqual(self.TagCode.branch_for(code), branch_12)
        code_1 = self.TagCode.format_number(self.branch_1, 2000001)
        self.assertEqual(self.TagCode.branch_for(code_1), self.branch_1)

    def test_without_check_digit(self):
        branch = self.Branch.create(
            {"name": "Test Plant 3", "code": "TP3", "tag_check_digit": False}
        )
        code = self.TagCode.generate(branch)
        self.assertEqual(len(code), len("TP3") + 7)
        self.assertTrue(self.TagCode.is_valid(code, branch))
        self.assertEqual(self.TagCode.branch_for(code), branch)

    def test_prefix_rules(self):
        branch = self.Branch.create(
            {"name": "Test Plant 4", "code": "TP4", "tag_prefix": " w4 "}
        )
        self.assertEqual(branch.tag_prefix, "W4")
        self.assertTrue(branch.tag_sequence_id)
        with self.assertRaises(ValidationError):
            branch.tag_prefix = "W-4"
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            branch.tag_prefix = "TP1"
            branch.flush_recordset()
