# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields
from odoo.tests import tagged

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestNumbering(LaundryJobCommon):
    def test_sequence_created_for_new_branch(self):
        branch = self.Branch.create({"name": "T Plant 3", "code": "tp3"})
        sequence = branch.laundry_job_sequence_id
        self.assertTrue(sequence)
        self.assertEqual(sequence.code, f"laundry.job.{branch.id}")
        self.assertEqual(sequence.prefix, "TP3/%(range_y)s/")
        self.assertEqual(sequence.padding, 5)
        self.assertTrue(sequence.use_date_range)

    def test_per_branch_numbering(self):
        year = fields.Date.today().strftime("%y")
        job_1 = self._create_job()
        job_2 = self._create_job()
        job_3 = self._create_job(branch=self.branch_2)
        self.assertEqual(job_1.name, f"TP1/{year}/00001")
        self.assertEqual(job_2.name, f"TP1/{year}/00002")
        self.assertEqual(job_3.name, f"TP2/{year}/00001")

    def test_code_change_updates_prefix(self):
        self.branch_2.code = "tpx"
        self.assertEqual(
            self.branch_2.laundry_job_sequence_id.prefix, "TPX/%(range_y)s/"
        )
