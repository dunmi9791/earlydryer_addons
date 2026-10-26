# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger
from psycopg2 import IntegrityError

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestItemsLock(LaundryJobCommon):
    def test_items_editable_while_received(self):
        job = self._create_job()
        item = job.item_ids.with_user(self.user_front_desk)
        item.write({"colour": "Blue", "brand": "Zara"})
        self.assertEqual(item.colour, "Blue")
        with self.assertRaises(AccessError):
            item.price_unit = 1

    def test_items_locked_after_intake(self):
        job = self._create_job()
        job.action_move_to("tagged")
        item = job.item_ids.with_user(self.user_front_desk)
        # allowed after intake (earlydryer_tagging, when installed, already
        # gave the garment a printed code that may only be kept or replaced)
        tag = item.tag_code or "T-0001"
        item.write({"tag_code": tag, "condition_note": "Torn pocket", "missing": False})
        self.assertEqual(item.tag_code, tag)
        with self.assertRaises(UserError):
            item.colour = "Red"
        with self.assertRaises(UserError):
            item.product_id = self.shirt_dc
        with self.assertRaises(UserError):
            job.with_user(self.user_front_desk).write(
                {"item_ids": [(0, 0, {"product_id": self.shirt_wi.id})]}
            )
        # a manager corrects with a reason
        manager_job = job.with_user(self.user_manager)
        with self.assertRaises(UserError):
            manager_job.item_ids.colour = "Red"
        manager_job.write(
            {
                "correction_reason": "Wrong colour at intake",
                "item_ids": [(1, item.id, {"colour": "Red"})],
            }
        )
        self.assertEqual(item.colour, "Red")
        self.assertIn("Wrong colour at intake", job.message_ids[0].body)

    def test_tag_unique_per_branch(self):
        duplicate_error = IntegrityError
        if "tag_mode" in self.Branch._fields:
            # earlydryer_tagging: free codes only on pre-printed plants, and
            # uniqueness is checked in Python (the unique index is replaced)
            (self.branch_1 | self.branch_2).write(
                {"tag_mode": "preprinted", "tag_preprinted_pattern": r"^A[0-9]+$"}
            )
            duplicate_error = ValidationError
        job_1 = self._create_job()
        job_2 = self._create_job()
        job_3 = self._create_job(branch=self.branch_2)
        job_1.item_ids.tag_code = "A1"
        job_3.item_ids.tag_code = "A1"
        with (
            self.assertRaises(duplicate_error),
            mute_logger("odoo.sql_db"),
            self.cr.savepoint(),
        ):
            job_2.item_ids.tag_code = "A1"
            job_2.item_ids.flush_recordset()
        # searching a job by tag
        self.assertEqual(
            self.Job.search([("item_ids.tag_code", "=", "A1")]), job_1 | job_3
        )

    def test_shelf_after_collection_manager_only(self):
        job = self._create_job()
        self.env.ref(
            "earlydryer_laundry_order.approval_rule_credit_laundry_job"
        ).active = False
        self._walk(job, [*self.PRODUCTION_PATH, "qc_pass", "packed"])
        job.shelf_id = self.branch_1.shelf_ids[0]
        job.action_move_to("ready")
        job.action_move_to("collected")
        with self.assertRaises(AccessError):
            job.with_user(self.user_front_desk).shelf_id = self.branch_1.shelf_ids[1]
        job.with_user(self.user_manager).shelf_id = self.branch_1.shelf_ids[1]

    def test_log_rows_are_read_only(self):
        job = self._create_job()
        log = job.stage_log_ids.with_user(self.user_manager)
        with self.assertRaises(AccessError):
            log.note = "changed"
        with self.assertRaises(AccessError):
            log.unlink()
        with self.assertRaises(AccessError):
            job.with_user(self.user_manager).unlink()
