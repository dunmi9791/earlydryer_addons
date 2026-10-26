# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import TaggingCommon


@tagged("post_install", "-at_install")
class TestScanLookup(TaggingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job = cls._create_job([(cls.shirt_wi, 2, None)])
        cls.code = cls.job.item_ids[0].tag_code

    def test_lookup_item(self):
        Job = self.Job.with_user(self.user_front_desk)
        res = Job.earlydryer_scan_lookup(f" {self.code.lower()} ")
        self.assertEqual(res["type"], "item")
        self.assertEqual(res["job_id"], self.job.id)
        self.assertEqual(res["item_id"], self.job.item_ids[0].id)
        self.assertEqual(res["job_name"], self.job.name)
        self.assertEqual(res["state"], "received")
        self.assertEqual(res["branch_id"], self.branch_1.id)
        log = self.ScanLog.search([("code", "=", self.code)], limit=1)
        self.assertEqual(
            (log.mode, log.result, log.job_id, log.user_id),
            ("find", "ok", self.job, self.user_front_desk),
        )
        # the rider can find
        res = self.Job.with_user(self.user_rider).earlydryer_scan_lookup(self.code)
        self.assertEqual(res["type"], "item")

    def test_lookup_job_number(self):
        res = self.Job.with_user(self.user_front_desk).earlydryer_scan_lookup(
            self.job.name
        )
        self.assertEqual(res["type"], "job")
        self.assertEqual(res["job_id"], self.job.id)
        self.assertFalse(res["item_id"])

    def test_invalid_check_digit_without_search(self):
        typo = self.code[:-1] + str((int(self.code[-1]) + 1) % 10)
        Job = self.Job.with_user(self.user_front_desk)
        Job._earlydryer_resolve(self.code)  # warm the prefix cache
        with self.assertQueryCount(0):
            kind, job, item = Job._earlydryer_resolve(typo)
        self.assertEqual(
            (kind, job, item), ("invalid", self.Job, self.env["laundry.job.item"])
        )
        res = Job.earlydryer_scan_lookup(typo)
        self.assertEqual(res["type"], "invalid")
        self.assertFalse(res["job_id"])

    def test_other_branch_hidden(self):
        job_2 = self._create_job(branch=self.branch_2)
        job_2.item_ids.tag_code = "TT3001"
        res = self.Job.with_user(self.user_front_desk).earlydryer_scan_lookup("TT3001")
        self.assertEqual(res["type"], "unknown")
        self.assertFalse(res["job_id"])
        self.assertNotIn(job_2.name, res["message"])
        res = self.Job.with_user(self.user_front_desk).earlydryer_scan_lookup(
            job_2.name
        )
        self.assertEqual(res["type"], "unknown")
        res = self.Job.with_user(self.user_front_desk_2).earlydryer_scan_lookup(
            "TT3001"
        )
        self.assertEqual(res["job_id"], job_2.id)

    def test_preprinted_reuse_finds_open_job(self):
        old = self._create_job(branch=self.branch_2)
        old.item_ids.tag_code = "TT3002"
        old.action_move_to("cancelled", note="T closed")
        new = self._create_job(branch=self.branch_2)
        new.item_ids.tag_code = "TT3002"
        res = self.Job.with_user(self.user_front_desk_2).earlydryer_scan_lookup(
            "TT3002"
        )
        self.assertEqual(res["job_id"], new.id)

    def test_replaced_tag_message(self):
        item = self.job.item_ids[1]
        old = item.tag_code
        new = item._earlydryer_replace_tag("Lost")
        res = self.Job.with_user(self.user_front_desk).earlydryer_scan_lookup(old)
        self.assertEqual(res["type"], "unknown")
        self.assertIn(new, res["message"])


@tagged("post_install", "-at_install")
class TestScanMove(TaggingCommon):
    def test_move_groups_by_job(self):
        job_a = self._create_job([(self.shirt_wi, 3, None)])
        job_b = self._create_job([(self.shirt_wi, 1, None)])
        Job = self.Job.with_user(self.user_front_desk)
        codes = job_a.item_ids[:2].mapped("tag_code") + job_b.item_ids.mapped(
            "tag_code"
        )
        codes.append(codes[0])  # scanned twice
        typo = codes[0][:-1] + str((int(codes[0][-1]) + 1) % 10)
        results = Job.earlydryer_scan_move(codes + [typo], "tagged", self.employee.id)
        self.assertEqual(len(results), 4, "duplicates are dropped")
        by_code = {r["code"]: r for r in results}
        self.assertEqual(by_code[typo]["result"], "invalid")
        for code in codes:
            self.assertEqual(by_code[code]["result"], "ok")
        self.assertEqual(job_a.state, "tagged")
        self.assertEqual(job_b.state, "tagged")
        log_a = self.Log.search(
            [("job_id", "=", job_a.id), ("to_state", "=", "tagged")]
        )
        self.assertEqual(len(log_a), 1, "one stage log row per job and move")
        self.assertEqual(log_a.item_ids, job_a.item_ids[:2])
        self.assertEqual(log_a.employee_id, self.employee)
        log_b = self.Log.search(
            [("job_id", "=", job_b.id), ("to_state", "=", "tagged")]
        )
        self.assertEqual(log_b.item_ids, job_b.item_ids)
        # job A still had an unscanned garment
        self.assertIn(job_a.item_ids[2].tag_code, by_code[codes[0]]["warning"])
        self.assertFalse(by_code[job_b.item_ids.tag_code]["warning"])
        scans = self.ScanLog.search(
            [("mode", "=", "move"), ("job_id", "in", (job_a | job_b).ids)]
        )
        self.assertEqual(len(scans), 3)

    def test_move_refused_and_noop(self):
        job = self._create_job()
        Job = self.Job.with_user(self.user_production)
        Job.earlydryer_scan_move([job.name], "tagged", False)
        self.assertEqual(job.state, "tagged")
        # Sorted needs who did the work
        res = Job.earlydryer_scan_move(job.item_ids.mapped("tag_code"), "sorted", False)
        self.assertEqual(res[0]["result"], "refused")
        self.assertEqual(job.state, "tagged")
        res = Job.earlydryer_scan_move(job.item_ids.mapped("tag_code"), "tagged", False)
        self.assertEqual(res[0]["result"], "duplicate")
        res = Job.earlydryer_scan_move(
            job.item_ids.mapped("tag_code"), "sorted", self.employee.id
        )
        self.assertEqual(res[0]["result"], "ok")
        self.assertEqual(job.state, "sorted")

    def test_rider_cannot_move(self):
        job = self._create_job()
        with self.assertRaises(AccessError):
            self.Job.with_user(self.user_rider).earlydryer_scan_move(
                job.item_ids.mapped("tag_code"), "tagged", False
            )
        with self.assertRaises(AccessError):
            self.Job.with_user(self.user_rider).earlydryer_scan_pack(
                job.id, job.item_ids.tag_code
            )

    def test_scan_context(self):
        ctx = self.Job.with_user(self.user_front_desk).earlydryer_scan_context()
        self.assertEqual([b["id"] for b in ctx["branches"]], [self.branch_1.id])
        self.assertIn(self.employee.id, [e["id"] for e in ctx["employees"]])
        self.assertNotIn(self.employee_2.id, [e["id"] for e in ctx["employees"]])
        self.assertTrue(ctx["rights"]["move"])
        self.assertFalse(ctx["rights"]["manager"])
        stages = [s[0] for s in ctx["stages"]]
        self.assertIn("sorted", stages)
        self.assertNotIn("received", stages)
        rider = self.Job.with_user(self.user_rider).earlydryer_scan_context()
        self.assertFalse(rider["rights"]["move"])
