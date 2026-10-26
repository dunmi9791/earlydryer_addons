# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import ProductionCommon


@tagged("post_install", "-at_install")
class TestBatch(ProductionCommon):
    def test_sequence_and_branch_setting(self):
        job = self._job_in("sorted")
        batch = self._batch(job.item_ids)
        self.assertTrue(batch.name.startswith(f"{self.branch_1.code}/WB/"))
        self.branch_1.use_wash_batches = False
        with self.assertRaises(UserError):
            self._batch(self.env["laundry.job.item"])

    def test_no_item_in_two_open_batches(self):
        job = self._job_in("sorted")
        first = self._batch(job.item_ids)
        with self.assertRaises(ValidationError):
            self._batch(job.item_ids)
        # a dry batch is another type: allowed once washed
        first.action_start()
        first.action_done()
        self.assertEqual(job.state, "washed")
        dry = self._batch(job.item_ids, "dry", self.dryer)
        self.assertEqual(dry.state, "draft")
        # once cancelled the garments are free again
        dry.action_cancel()
        self._batch(job.item_ids, "dry", self.dryer)

    def test_machine_type_must_match(self):
        job = self._job_in("sorted")
        with self.assertRaises(ValidationError):
            self._batch(job.item_ids, "wash", self.dryer)

    def test_down_machine_needs_manager_override(self):
        job = self._job_in("sorted")
        self.Request.create(
            {
                "name": "Broken",
                "equipment_id": self.washer.id,
                "maintenance_type": "corrective",
                "maintenance_team_id": self.team.id,
            }
        )
        batch = self._batch(job.item_ids).with_user(self.user_production)
        with self.assertRaisesRegex(UserError, "down"):
            batch.action_start()
        as_manager = batch.with_user(self.user_manager)
        with self.assertRaisesRegex(UserError, "override"):
            as_manager.action_start()
        as_manager.override_note = "Only the door sensor, tested OK"
        as_manager.action_start()
        self.assertEqual(batch.state, "running")
        self.assertIn("despite", batch.message_ids[0].body)

    def test_busy_machine_refused(self):
        job_a, job_b = self._job_in("sorted"), self._job_in("sorted")
        self._batch(job_a.item_ids).action_start()
        batch = self._batch(job_b.item_ids).with_user(self.user_production)
        with self.assertRaisesRegex(UserError, "already running"):
            batch.action_start()

    def test_done_moves_only_fully_covered_jobs(self):
        job_full = self._job_in("sorted")
        job_split = self._job_in("sorted", [(self.shirt_wi, 2, None)])
        other_employee = self.Employee.create(
            {"name": "T Loader", "earlydryer_branch_id": self.branch_1.id}
        )
        batch = self._batch(
            job_full.item_ids | job_split.item_ids[0], employee_id=other_employee.id
        ).with_user(self.user_production)
        batch.action_start()
        batch.action_done()
        self.assertEqual(job_full.state, "washed")
        self.assertEqual(job_split.state, "sorted")
        log = self._last_log(job_full)
        self.assertEqual((log.employee_id, log.source), (other_employee, "batch"))
        self.assertEqual(log.item_ids, job_full.item_ids)
        card = job_split._earlydryer_board_card()
        self.assertEqual(card["batch_progress"], "1/2 washed")
        # the second garment's batch completes the job
        second = self._batch(job_split.item_ids[1]).with_user(self.user_production)
        second.action_start()
        second.action_done()
        self.assertEqual(job_split.state, "washed")
        self.assertEqual(self._last_log(job_split).employee_id, self.employee)

    def test_skipped_stage_items_ignored(self):
        # ironing-only garments never go through a wash
        job = self._job_in(
            "sorted", [(self.shirt_wi, 1, None), (self.shirt_io, 1, None)]
        )
        washable = job.item_ids.filtered(lambda i: i.product_id == self.shirt_wi)
        batch = self._batch(washable)
        batch.action_start()
        batch.action_done()
        self.assertEqual(job.state, "washed")

    def test_no_move_when_setting_off(self):
        self.branch_1.batch_moves_stage = False
        job = self._job_in("sorted")
        batch = self._batch(job.item_ids)
        batch.action_start()
        batch.action_done()
        self.assertEqual(job.state, "sorted")
        self.assertTrue(batch.finished_on)

    def test_load_weight_required(self):
        self.branch_1.require_load_weight = True
        job = self._job_in("sorted")
        batch = self._batch(job.item_ids)
        with self.assertRaisesRegex(UserError, "weight"):
            batch.action_start()
        batch.load_weight_kg = 3.2
        batch.action_start()
        self.assertEqual(batch.state, "running")

    def test_front_desk_reads_only(self):
        job = self._job_in("sorted")
        batch = self._batch(job.item_ids)
        batch.with_user(self.user_front_desk).read(["name"])
        with self.assertRaises(AccessError):
            batch.with_user(self.user_front_desk).action_start()
        with self.assertRaises(AccessError):
            self.Batch.with_user(self.user_front_desk).create(
                {"earlydryer_branch_id": self.branch_1.id}
            )

    def test_suggest_items(self):
        self.cat_shirt.average_weight_kg = 0.5
        jobs = self._job_in("sorted", [(self.shirt_wi, 3, None)])
        express = self._job_in("sorted", [(self.shirt_wi, 2, None)], express=True)
        busy = self._job_in("sorted")
        self._batch(busy.item_ids)
        batch = self._batch(self.env["laundry.job.item"], colour_group="whites")
        batch.action_suggest_items()
        # 2 kg capacity / 0.5 kg: four garments, express first, the busy one left
        self.assertEqual(len(batch.item_ids), 4)
        self.assertEqual(batch.item_ids & express.item_ids, express.item_ids)
        self.assertFalse(batch.item_ids & busy.item_ids)
        self.assertLessEqual(len(batch.item_ids & jobs.item_ids), 2)
        # unknown weights: up to the count entered
        self.cat_shirt.average_weight_kg = 0
        batch.write({"item_ids": [(5,)], "suggest_count": 3})
        batch.action_suggest_items()
        self.assertEqual(len(batch.item_ids), 3)
