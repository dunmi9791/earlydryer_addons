# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ProductionCommon

PIXEL = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
)


@tagged("post_install", "-at_install")
class TestQc(ProductionCommon):
    def test_fail_stores_reason_and_return_state(self):
        job = self._job_in("qc", [(self.shirt_wi, 2, None)])
        first, second = job.item_ids
        reworks = job.with_user(self.user_qc).action_qc_fail(
            second, self.employee, reason=self.reason_stain, photo=PIXEL
        )
        self.assertEqual(job.state, "sorted")
        self.assertEqual(second.qc_state, "rework")
        self.assertEqual(second.rework_count, 1)
        self.assertEqual(first.qc_state, "pending")
        self.assertEqual(reworks.item_id, second)
        self.assertEqual(reworks.reason_id, self.reason_stain)
        self.assertEqual((reworks.from_state, reworks.to_state), ("qc", "sorted"))
        self.assertEqual(reworks.employee_id, self.employee)
        self.assertTrue(reworks.photo_id)
        self.assertIn(reworks.photo_id, second.photo_ids)
        log = self._last_log(job)
        self.assertEqual((log.source, log.item_ids), ("qc", second))
        self.assertIn("T Stain", log.note)

    def test_reason_required(self):
        job = self._job_in("qc")
        with self.assertRaisesRegex(UserError, "rework reason"):
            job.action_qc_fail(job.item_ids, self.employee, "washed", "Dirty")
        self.branch_1.qc_reason_required = False
        job.action_qc_fail(job.item_ids, self.employee, "washed", "Dirty")
        self.assertEqual(job.state, "washed")

    def test_damage_fires_hook_and_activity(self):
        self.branch_1.manager_id = self.user_manager
        job = self._job_in("qc")
        Job = type(self.Job)
        with patch.object(Job, "_earlydryer_on_damage_found", autospec=True) as hook:
            reworks = job.with_user(self.user_qc).action_qc_fail(
                job.item_ids, self.employee, reason=self.reason_damage
            )
        hook.assert_called_once()
        self.assertEqual(hook.call_args.args[1], reworks)
        self.assertEqual(job.state, "ironed")
        activity = job.activity_ids.filtered(lambda a: "Damage" in a.summary)
        self.assertEqual(activity.user_id, self.user_manager)
        self.assertTrue(
            job.message_ids.filtered(lambda m: "Damage found" in (m.body or ""))
        )
        self.assertTrue(reworks.is_damage)

    def test_wizard_per_item_and_earliest_return(self):
        job = self._job_in("qc", [(self.shirt_wi, 3, None)])
        action = self.Job.with_user(self.user_qc).earlydryer_board_open_qc(
            job.id, employee_id=self.employee.id
        )
        wizard = (
            self.env["earlydryer.qc.wizard"]
            .with_user(self.user_qc)
            .with_context(**action["context"])
            .create({})
        )
        lines = wizard.line_ids
        lines[1].write({"result": "fail", "reason_id": self.reason_iron.id})
        lines[2].write(
            {"result": "fail", "reason_id": self.reason_stain.id, "note": "Collar"}
        )
        self.assertEqual(lines[1].return_state, "ironed")
        wizard.with_user(self.user_qc).action_confirm()
        self.assertEqual(job.state, "sorted")
        self.assertEqual(lines[0].item_id.qc_state, "passed")
        reworks = job.rework_ids
        self.assertEqual(len(reworks), 2)
        self.assertEqual(set(reworks.mapped("to_state")), {"sorted"})
        self.assertEqual(
            reworks.filtered(lambda r: r.item_id == lines[2].item_id).note, "Collar"
        )

    def test_all_passed_leads_to_packing(self):
        job = self._job_in("qc", [(self.shirt_wi, 2, None)])
        action = self.Job.with_user(self.user_qc).earlydryer_board_open_qc(
            job.id, employee_id=self.employee.id
        )
        wizard = (
            self.env["earlydryer.qc.wizard"]
            .with_user(self.user_qc)
            .with_context(**action["context"])
            .create({})
        )
        wizard.with_user(self.user_qc).action_confirm_pack()
        self.assertEqual(job.state, "packed")
        self.assertEqual(self._last_log(job).source, "qc")

    def test_pack_opens_scan_screen_when_scanning_required(self):
        self.branch_1.tag_require_packing_scan = True
        job = self._job_in("qc")
        job.action_qc_pass(employee=self.employee)
        action = job.action_earlydryer_qc_pack(self.employee)
        self.assertEqual(action["tag"], "earlydryer_tagging.scan_screen")
        self.assertEqual(job.state, "qc")

    def test_front_desk_cannot_qc(self):
        job = self._job_in("qc")
        with self.assertRaises(AccessError):
            job.with_user(self.user_front_desk).action_qc_pass(employee=self.employee)
        with self.assertRaises(AccessError):
            self.Job.with_user(self.user_front_desk).earlydryer_board_open_qc(job.id)
