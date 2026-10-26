# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestStageMoves(LaundryJobCommon):
    def test_forward_moves_log_employee_and_user(self):
        job = self._create_job()
        job_fd = job.with_user(self.user_front_desk)
        self._walk(job_fd, self.PRODUCTION_PATH)
        # the quality check itself is QC's job (earlydryer_production enforces it)
        job.with_user(self.user_qc).action_qc_pass(employee=self.employee)
        self._walk(job_fd, ["packed"])
        self.assertEqual(job.state, "packed")
        logs = job.stage_log_ids.filtered("from_state").sorted("id")
        self.assertEqual(
            logs.mapped("to_state"),
            ["tagged", "sorted", "washed", "dried", "ironed", "qc", "packed"],
        )
        self.assertEqual(logs.employee_id, self.employee)
        self.assertEqual(logs.user_id, self.user_front_desk)
        self.assertEqual(
            logs.mapped("from_state"),
            ["received", "tagged", "sorted", "washed", "dried", "ironed", "qc"],
        )
        self.assertTrue(all(log.duration_hours >= 0 for log in logs))

    def test_employee_required_on_production_stages(self):
        job = self._create_job()
        # tagged does not need an employee
        job.with_user(self.user_front_desk).action_move_to("tagged")
        with self.assertRaises(UserError):
            job.with_user(self.user_front_desk).action_move_to("sorted")
        job.with_user(self.user_front_desk).action_move_to(
            "sorted", employee=self.employee.id
        )
        self.assertEqual(job.state, "sorted")

    def test_backward_move(self):
        job = self._create_job()
        self._walk(job.with_user(self.user_front_desk), ["tagged", "sorted", "washed"])
        with self.assertRaises(AccessError):
            job.with_user(self.user_front_desk).action_move_to(
                "sorted", employee=self.employee, note="Stain left"
            )
        manager_job = job.with_user(self.user_manager)
        with self.assertRaises(UserError):
            manager_job.action_move_to("sorted", employee=self.employee)
        manager_job.action_move_to("sorted", employee=self.employee, note="Stain left")
        self.assertEqual(job.state, "sorted")
        self.assertEqual(self._last_log(job).note, "Stain left")
        self.assertEqual(self._last_log(job).user_id, self.user_manager)

    def test_batch_and_idempotent_moves(self):
        jobs = self._create_job() | self._create_job()
        jobs.with_user(self.user_front_desk).action_move_to("tagged")
        self.assertEqual(set(jobs.mapped("state")), {"tagged"})
        count = self.Log.search_count([("job_id", "in", jobs.ids)])
        self.assertEqual(count, 4)
        # same target again: nothing happens
        jobs.with_user(self.user_front_desk).action_move_to("tagged")
        self.assertEqual(self.Log.search_count([("job_id", "in", jobs.ids)]), count)

    def test_state_only_through_moves(self):
        job = self._create_job()
        with self.assertRaises(UserError):
            job.with_user(self.user_front_desk).write({"state": "ready"})

    def test_service_skip(self):
        # ironing only: no washing or drying
        job = self._create_job([(self.shirt_io, 1, None)])
        self._walk(job.with_user(self.user_front_desk), ["tagged", "sorted"])
        self.assertEqual(job.next_state, "ironed")
        job.with_user(self.user_front_desk).action_move_to(
            "ironed", employee=self.employee
        )
        self.assertEqual(job.state, "ironed")

    def test_invalid_skip_refused(self):
        # a wash & iron item cannot skip washing
        job = self._create_job([(self.shirt_io, 1, None), (self.shirt_wi, 1, None)])
        self._walk(job.with_user(self.user_front_desk), ["tagged", "sorted"])
        self.assertEqual(job.next_state, "washed")
        with self.assertRaises(AccessError):
            job.with_user(self.user_front_desk).action_move_to(
                "ironed", employee=self.employee
            )
        # a manager may, with a note
        job.with_user(self.user_manager).action_move_to(
            "ironed", employee=self.employee, note="Washed by the customer"
        )
        self.assertEqual(job.state, "ironed")

    def test_ready_requires_shelf_of_same_branch(self):
        job = self._create_job()
        self._walk(job, [*self.PRODUCTION_PATH, "qc_pass", "packed"])
        with self.assertRaises(UserError):
            job.action_move_to("ready", employee=self.employee)
        with self.assertRaises(UserError):
            job.shelf_id = self.branch_2.shelf_ids[:1]
        job.shelf_id = self.branch_1.shelf_ids[:1]
        job.action_move_to("ready", employee=self.employee)
        self.assertEqual(job.state, "ready")
        self.assertTrue(job.ready_on)

    def test_move_wizard(self):
        job = self._create_job()
        job.with_user(self.user_front_desk).action_move_to("tagged")
        action = job.with_user(self.user_front_desk).action_next_stage()
        self.assertEqual(action["res_model"], "laundry.job.move.wizard")
        wizard = (
            self.env["laundry.job.move.wizard"]
            .with_user(self.user_front_desk)
            .with_context(action["context"])
            .create({"employee_id": self.employee.id})
        )
        self.assertEqual(wizard.target_state, "sorted")
        wizard.action_confirm()
        self.assertEqual(job.state, "sorted")
        self.assertEqual(self._last_log(job).employee_id, self.employee)
