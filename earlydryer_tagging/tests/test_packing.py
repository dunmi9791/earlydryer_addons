# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import TaggingCommon


@tagged("post_install", "-at_install")
class TestPacking(TaggingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job = cls._job_qc_passed([(cls.shirt_wi, 3, None)])
        cls.other = cls._job_qc_passed([(cls.shirt_wi, 1, None)])

    def _pack(self, code, user=None, job=None):
        Job = self.Job.with_user(user or self.user_front_desk)
        return Job.earlydryer_scan_pack((job or self.job).id, code, self.employee.id)

    def test_pack_scan_results(self):
        items = self.job.item_ids
        res = self.Job.with_user(self.user_front_desk).earlydryer_pack_start(
            self.job.name
        )
        self.assertEqual((res["result"], res["scanned"], res["expected"]), ("ok", 0, 3))
        res = self._pack(items[0].tag_code)
        self.assertEqual(res["result"], "ok")
        self.assertTrue(items[0].packed_scanned)
        self.assertTrue(items[0].packed_scanned_on)
        self.assertEqual((res["scanned"], res["expected"]), (1, 3))
        self.assertEqual(
            {m["code"] for m in res["missing_items"]}, set(items[1:].mapped("tag_code"))
        )
        self.assertEqual(self._pack(items[0].tag_code)["result"], "duplicate")
        code = items[0].tag_code
        typo = code[:-1] + str((int(code[-1]) + 1) % 10)
        self.assertEqual(self._pack(typo)["result"], "invalid")
        self.assertEqual(self._pack("ZZ0000")["result"], "unknown")
        # own bag label: fine
        res = self._pack(self.job.name)
        self.assertEqual((res["result"], res["bag"]), ("ok", True))

    def test_wrong_job_alerts(self):
        res = self._pack(self.other.item_ids.tag_code)
        self.assertEqual(res["result"], "wrong_job")
        self.assertEqual(res["other_job_name"], self.other.name)
        self.assertFalse(self.other.item_ids.packed_scanned)
        log = self.ScanLog.search(
            [("code", "=", self.other.item_ids.tag_code)], limit=1
        )
        self.assertTrue(log.is_mismatch)
        self.assertEqual(log.expected_job_id, self.job)
        self.assertEqual(log.job_id, self.other)
        activity = self.env["mail.activity"].search(
            [("res_model", "=", "laundry.job"), ("res_id", "=", self.job.id)]
        )
        self.assertEqual(activity.user_id, self.user_manager)
        self.assertIn("mismatch", activity.summary.lower())
        self.assertIn(self.other.item_ids.tag_code, self.job.message_ids[0].body)
        self.assertIn(self.other.item_ids.tag_code, self.other.message_ids[0].body)

    def test_other_bag_label_no_alert(self):
        res = self._pack(self.other.name)
        self.assertEqual((res["result"], res["bag"]), ("wrong_job", True))
        self.assertEqual(res["other_job_name"], self.other.name)
        activity = self.env["mail.activity"].search(
            [("res_model", "=", "laundry.job"), ("res_id", "=", self.job.id)]
        )
        self.assertFalse(activity)

    def test_wrong_branch(self):
        job_2 = self._job_qc_passed(branch=self.branch_2)
        res = self._pack(job_2.item_ids.tag_code)
        self.assertEqual(res["result"], "wrong_branch")
        self.assertFalse(res["other_job_name"], "the other plant's job stays hidden")
        log = self.ScanLog.search([("code", "=", job_2.item_ids.tag_code)], limit=1)
        self.assertTrue(log.is_mismatch)

    def test_all_scanned_gate(self):
        items = self.job.item_ids
        for item in items[:2]:
            self._pack(item.tag_code)
        with self.assertRaisesRegex(UserError, "Scan every garment"):
            self.job.action_move_to("packed", employee=self.employee)
        with self.assertRaises(UserError):
            self.Job.with_user(self.user_front_desk).earlydryer_pack_finish(
                self.job.id, self.employee.id
            )
        self._pack(items[2].tag_code)
        res = self.Job.with_user(self.user_front_desk).earlydryer_pack_finish(
            self.job.id, self.employee.id
        )
        self.assertEqual(res["result"], "ok")
        self.assertEqual(self.job.state, "packed")
        log = self.Log.search(
            [("job_id", "=", self.job.id), ("to_state", "=", "packed")]
        )
        self.assertEqual(log.item_ids, items)

    def test_gate_off(self):
        self.branch_1.tag_require_packing_scan = False
        self.job.action_move_to("packed", employee=self.employee)
        self.assertEqual(self.job.state, "packed")

    def test_manager_marks_missing(self):
        items = self.job.item_ids
        self._pack(items[0].tag_code)
        with self.assertRaises(AccessError):
            self.Job.with_user(self.user_front_desk).earlydryer_pack_finish(
                self.job.id, self.employee.id, note="gone", mark_missing=True
            )
        Job = self.Job.with_user(self.user_manager)
        with self.assertRaises(UserError):
            Job.earlydryer_pack_finish(self.job.id, self.employee.id, mark_missing=True)
        res = Job.earlydryer_pack_finish(
            self.job.id, self.employee.id, note="Not on the rail", mark_missing=True
        )
        self.assertEqual(res["result"], "missing_marked")
        self.assertEqual(items.mapped("missing"), [False, True, True])
        self.assertEqual((res["scanned"], res["expected"]), (1, 1))
        # laundry_order never packs a job with missing items
        with self.assertRaisesRegex(UserError, "missing"):
            self.job.action_move_to("packed", employee=self.employee)
        # a missing garment found and scanned is back
        res = self._pack(items[1].tag_code)
        self.assertEqual(res["result"], "ok")
        self.assertFalse(items[1].missing)

    def test_rework_resets_scans(self):
        items = self.job.item_ids
        self._pack(items[0].tag_code)
        self._pack(items[1].tag_code)
        self.job.action_qc_fail(items[2], self.employee, "washed", "Stain left")
        self.assertEqual(self.job.state, "washed")
        self.assertFalse(any(items.mapped("packed_scanned")))
        with self.assertRaises(UserError):
            self._pack(items[0].tag_code)

    def test_pack_refused_before_qc(self):
        job = self._create_job()
        with self.assertRaisesRegex(UserError, "after QC"):
            self.Job.with_user(self.user_front_desk).earlydryer_pack_start(job.name)
