# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import TaggingCommon


@tagged("post_install", "-at_install")
class TestTagAssign(TaggingCommon):
    def test_auto_assign_at_creation(self):
        job = self._create_job([(self.suit_dc, 1, None), (self.shirt_wi, 2, None)])
        self.assertEqual(len(job.item_ids), 4, "2-piece suit + 2 shirts")
        self.assertTrue(all(job.item_ids.mapped("tag_code")))
        self.assertEqual(len(set(job.item_ids.mapped("tag_code"))), 4)
        self.assertEqual(job.state, "received")
        self.assertTrue(job._check_can_tag())

    def test_tagged_refused_while_item_lacks_code(self):
        self.branch_1.tag_auto_assign = False
        job = self._create_job([(self.shirt_wi, 2, None)])
        self.assertEqual(job.tag_missing_count, 2)
        self.assertFalse(job._check_can_tag())
        with self.assertRaisesRegex(UserError, "Tag every item"):
            job.action_move_to("tagged")
        job.item_ids[0].tag_code = self.TagCode.generate(self.branch_1)
        self.assertFalse(job._check_can_tag())
        job.with_user(self.user_front_desk).action_assign_tags()
        self.assertEqual(job.tag_missing_count, 0)
        self.assertEqual(job.state, "tagged", "assign moves the job to Tagged")

    def test_service_without_tag(self):
        self.svc_dc.requires_tag = False
        self.branch_1.tag_auto_assign = False
        job = self._create_job([(self.shirt_dc, 1, None), (self.shirt_wi, 1, None)])
        untagged = job.item_ids.filtered(lambda i: i.product_id == self.shirt_dc)
        job.with_user(self.user_front_desk).action_assign_tags()
        self.assertFalse(untagged.tag_code)
        self.assertEqual(job.state, "tagged")

    def test_assign_and_print(self):
        self.branch_1.tag_auto_assign = False
        job = self._create_job([(self.shirt_wi, 2, None)])
        action = job.with_user(self.user_front_desk).action_assign_and_print_tags()
        self.assertEqual(action["type"], "ir.actions.report")
        self.assertEqual(action["report_name"], "earlydryer_tagging.report_garment_tag")
        self.assertEqual(
            sorted(action["context"]["active_ids"]), sorted(job.item_ids.ids)
        )
        self.assertEqual(job.state, "tagged")
        self.assertEqual(job.item_ids.mapped("tag_print_count"), [1, 1])

    def test_reprint_logged(self):
        job = self._create_job()
        job.with_user(self.user_front_desk).action_assign_and_print_tags()
        messages = job.message_ids
        job.with_user(self.user_production).action_reprint_tags()
        new = job.message_ids - messages
        self.assertIn("reprinted by", new.body)
        self.assertIn(self.user_production.name, new.body)
        self.assertEqual(job.item_ids.tag_print_count, 2)

    def test_rights(self):
        job = self._create_job()
        with self.assertRaises(AccessError):
            job.with_user(self.user_production).action_assign_tags()
        with self.assertRaises(AccessError):
            job.with_user(self.user_rider).action_reprint_tags()
        # typing over a tag is a replacement
        with self.assertRaises(AccessError):
            job.item_ids.with_user(self.user_front_desk).tag_code = False

    def test_batch_print(self):
        self.branch_1.tag_auto_assign = False
        jobs = self._create_job() | self._create_job()
        action = jobs.with_user(self.user_front_desk).action_print_tags()
        self.assertEqual(len(action["context"]["active_ids"]), 2)
        self.assertEqual(set(jobs.mapped("state")), {"tagged"})

    def test_preprinted_wizard(self):
        job = self._create_job([(self.suit_dc, 1, None)], branch=self.branch_2)
        self.assertEqual(job.tag_missing_count, 2)
        action = job.with_user(self.user_front_desk_2).action_assign_tags()
        self.assertEqual(action["res_model"], "earlydryer.tag.assign.wizard")
        wizard = (
            self.env[action["res_model"]]
            .browse(action["res_id"])
            .with_user(self.user_front_desk_2)
        )
        self.assertEqual(wizard.line_ids.item_id, job.item_ids)
        wizard.line_ids[0].tag_code = "TT1001"
        wizard.line_ids[1].tag_code = "TT1001"
        with self.assertRaisesRegex(UserError, "twice"):
            wizard.action_confirm()
        wizard.line_ids[1].tag_code = "tt1002"
        wizard.action_confirm()
        self.assertEqual(sorted(job.item_ids.mapped("tag_code")), ["TT1001", "TT1002"])
        self.assertEqual(job.state, "tagged")
        logs = self.ScanLog.search([("job_id", "=", job.id), ("mode", "=", "assign")])
        self.assertEqual(len(logs), 2)
