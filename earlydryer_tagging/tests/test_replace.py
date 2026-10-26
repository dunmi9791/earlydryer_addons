# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import TaggingCommon


@tagged("post_install", "-at_install")
class TestTagReplace(TaggingCommon):
    def test_printed_replace_by_manager(self):
        job = self._create_job()
        item = job.item_ids
        old = item.tag_code
        with self.assertRaises(AccessError):
            item.with_user(self.user_front_desk)._earlydryer_replace_tag("Lost")
        with self.assertRaises(UserError):
            item.with_user(self.user_manager)._earlydryer_replace_tag(" ")
        new = item.with_user(self.user_manager)._earlydryer_replace_tag("Tag torn off")
        self.assertNotEqual(new, old)
        self.assertEqual(item.tag_code, new)
        self.assertTrue(self.TagCode.is_valid(new, self.branch_1))
        history = item.tag_history_ids
        self.assertEqual(len(history), 1)
        self.assertEqual(
            (history.old_code, history.new_code, history.reason, history.user_id),
            (old, new, "Tag torn off", self.user_manager),
        )
        self.assertIn(old, job.message_ids[0].body)
        self.assertIn(new, job.message_ids[0].body)
        # the old code stays reserved
        other = self._create_job()
        with self.assertRaisesRegex(ValidationError, "reserved"):
            other.item_ids.tag_code = old
        # and the history cannot be changed
        with self.assertRaises(AccessError):
            history.with_user(self.user_manager).reason = "x"

    def test_replace_wizard(self):
        job = self._create_job()
        item = job.item_ids
        old = item.tag_code
        action = item.with_user(self.user_manager).action_open_replace_tag_wizard()
        wizard = (
            self.env[action["res_model"]]
            .with_user(self.user_manager)
            .create({"item_id": item.id, "reason": "Unreadable"})
        )
        print_action = wizard.action_confirm()
        self.assertEqual(print_action["type"], "ir.actions.report")
        self.assertNotEqual(item.tag_code, old)

    def test_preprinted_replace_by_front_desk(self):
        job = self._create_job(branch=self.branch_2)
        item = job.item_ids
        item.tag_code = "TT2001"
        as_desk = item.with_user(self.user_front_desk_2)
        with self.assertRaisesRegex(UserError, "Scan the new"):
            as_desk._earlydryer_replace_tag("Lost")
        as_desk._earlydryer_replace_tag("Lost", "TT2002")
        self.assertEqual(item.tag_code, "TT2002")
        self.assertEqual(item.tag_history_ids.old_code, "TT2001")
        # pre-printed tags are reusable: the old one can go on another open job
        other = self._create_job(branch=self.branch_2)
        other.item_ids.tag_code = "TT2001"

    def test_production_cannot_replace(self):
        job = self._create_job()
        with self.assertRaises(AccessError):
            job.item_ids.with_user(
                self.user_production
            ).action_open_replace_tag_wizard()
