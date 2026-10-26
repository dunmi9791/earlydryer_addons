# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TaggingCommon


@tagged("post_install", "-at_install")
class TestTagUniqueness(TaggingCommon):
    def test_laundry_order_unique_index_replaced(self):
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
            ["laundry_job_item_tag_branch_uniq"],
        )
        indexdef = self.env.cr.fetchone()[0]
        self.assertNotIn("UNIQUE", indexdef.upper())
        self.assertIn("tag_code", indexdef)

    def test_printed_codes_never_reused(self):
        job_a = self._create_job()
        job_b = self._create_job()
        code_a = job_a.item_ids.tag_code
        self.assertTrue(code_a)
        with self.assertRaisesRegex(ValidationError, job_a.name):
            job_b.item_ids.tag_code = code_a
        # still refused once job A is closed
        job_a.action_move_to("cancelled", note="T test")
        with self.assertRaises(ValidationError):
            job_b.item_ids.tag_code = code_a

    def test_printed_code_format(self):
        job = self._create_job()
        code = job.item_ids.tag_code
        typo = code[:-1] + str((int(code[-1]) + 1) % 10)
        job.item_ids.tag_code = False
        with self.assertRaisesRegex(ValidationError, "check digit"):
            job.item_ids.tag_code = typo
        with self.assertRaises(ValidationError):
            # a code of another plant
            job.item_ids.tag_code = "TP2" + code[3:]

    def test_preprinted_reuse_after_close(self):
        job_a = self._create_job(branch=self.branch_2)
        job_b = self._create_job(branch=self.branch_2)
        self.assertFalse(job_a.item_ids.tag_code, "no auto-assign for pre-printed tags")
        job_a.item_ids.tag_code = "tt0001"
        self.assertEqual(job_a.item_ids.tag_code, "TT0001")
        with self.assertRaisesRegex(ValidationError, job_a.name):
            job_b.item_ids.tag_code = "TT0001"
        job_a.action_move_to("cancelled", note="T closed")
        job_b.item_ids.tag_code = "TT0001"
        self.assertEqual(job_b.item_ids.tag_code, "TT0001")

    def test_preprinted_pattern(self):
        job = self._create_job(branch=self.branch_2)
        with self.assertRaisesRegex(ValidationError, "does not look like"):
            job.item_ids.tag_code = "AB12"
