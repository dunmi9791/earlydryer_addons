# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import TaggingCommon


@tagged("post_install", "-at_install")
class TestTagRanges(TaggingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.till = cls.env["pos.config"].create(
            {"name": "T Till P1", "earlydryer_branch_id": cls.branch_1.id}
        )

    def test_allocation_takes_a_block(self):
        first = self.branch_1._earlydryer_tag_next_number()
        tag_range = self.Range._earlydryer_allocate_range(self.branch_1, self.till, 50)
        self.assertEqual(tag_range.start_number, first)
        self.assertEqual(tag_range.end_number, first + 49)
        self.assertEqual(tag_range.next_number, first)
        self.assertEqual(tag_range.remaining_count, 50)
        self.assertEqual(
            tag_range.first_code, self.TagCode.format_number(self.branch_1, first)
        )
        # the server's next code comes after the block: no collision
        code = self.TagCode.generate(self.branch_1)
        self.assertEqual(self.TagCode.number_for(code, self.branch_1), first + 50)
        other = self.Range._earlydryer_allocate_range(self.branch_1, self.till, 10)
        self.assertEqual(other.start_number, first + 51)

    def test_no_overlap(self):
        tag_range = self.Range._earlydryer_allocate_range(self.branch_1, self.till, 10)
        with self.assertRaises(ValidationError):
            self.Range.create(
                {
                    "branch_id": self.branch_1.id,
                    "start_number": tag_range.end_number,
                    "end_number": tag_range.end_number + 5,
                    "next_number": tag_range.end_number,
                }
            )
        # another plant may use the same numbers (other prefix)
        self.Range.create(
            {
                "branch_id": self.branch_2.id,
                "start_number": tag_range.start_number,
                "end_number": tag_range.end_number,
                "next_number": tag_range.start_number,
            }
        )

    def test_consume_advances_and_exhausts(self):
        tag_range = self.Range._earlydryer_allocate_range(self.branch_1, self.till, 3)
        self.branch_1.tag_auto_assign = False
        job = self._create_job([(self.shirt_wi, 3, None)])
        items = job.item_ids
        codes = [
            self.TagCode.format_number(self.branch_1, tag_range.start_number + i)
            for i in range(3)
        ]
        items[0].tag_code = codes[0]
        self.assertEqual(tag_range.next_number, tag_range.start_number + 1)
        self.assertEqual(tag_range.state, "active")
        # out of order (offline sync): next number follows the highest
        items[2].tag_code = codes[2]
        self.assertEqual(tag_range.state, "exhausted")
        self.assertEqual(tag_range.remaining_count, 0)
        items[1].tag_code = codes[1]
        self.assertEqual(tag_range.next_number, tag_range.end_number + 1)

    def test_consume_refuses_unissued_and_cancelled(self):
        self.branch_1.tag_auto_assign = False
        job = self._create_job()
        future = self.branch_1._earlydryer_tag_next_number() + 100
        with self.assertRaisesRegex(ValidationError, "never issued"):
            job.item_ids.tag_code = self.TagCode.format_number(self.branch_1, future)
        tag_range = self.Range._earlydryer_allocate_range(self.branch_1, self.till, 5)
        tag_range.action_cancel()
        with self.assertRaisesRegex(ValidationError, "cancelled"):
            job.item_ids.tag_code = self.TagCode.format_number(
                self.branch_1, tag_range.start_number
            )
        # a code the server issued (outside any range) is fine
        code = self.TagCode.generate(self.branch_1)
        job.item_ids.tag_code = code
        self.assertEqual(job.item_ids.tag_code, code)

    def test_top_up_below_20_percent(self):
        new = self.Range._earlydryer_top_up(self.till)
        self.assertEqual(len(new), 1, "a till without range gets one")
        self.assertFalse(self.Range._earlydryer_top_up(self.till))
        tag_range = new
        tag_range.next_number = tag_range.end_number - 99  # 100 of 500 left: 20%
        self.assertFalse(self.Range._earlydryer_top_up(self.till))
        tag_range.next_number = tag_range.end_number - 98  # 99 left
        topped = self.Range._earlydryer_top_up(self.till)
        self.assertEqual(len(topped), 1)
        self.assertEqual(topped.pos_config_id, self.till)
        self.assertEqual(topped.size, 500)
        self.assertGreater(topped.start_number, tag_range.end_number)

    def test_top_up_ignores_preprinted(self):
        till_2 = self.env["pos.config"].create(
            {"name": "T Till P2", "earlydryer_branch_id": self.branch_2.id}
        )
        self.assertFalse(self.Range._earlydryer_top_up(till_2))
        with self.assertRaises(UserError):
            self.Range._earlydryer_allocate_range(self.branch_2, till_2)

    def test_rights(self):
        with self.assertRaises(AccessError):
            self.Range.with_user(self.user_front_desk)._earlydryer_allocate_range(
                self.branch_1, self.till
            )
        tag_range = self.Range.with_user(self.user_manager)._earlydryer_allocate_range(
            self.branch_1, self.till
        )
        self.assertEqual(tag_range.allocated_by, self.user_manager)
        self.assertTrue(tag_range.with_user(self.user_front_desk).read(["name"]))
        with self.assertRaises(AccessError):
            tag_range.with_user(self.user_front_desk).action_cancel()
