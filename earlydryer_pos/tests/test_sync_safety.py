# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.earlydryer_pos.models.pos_order import PosOrder
from odoo.addons.queue_job.tests.common import trap_jobs

from .common import EarlydryerPosCommon


@tagged("post_install", "-at_install")
class TestSyncSafety(EarlydryerPosCommon):
    def test_sync_twice_one_job(self):
        payload = self._payload([self._line(self.shirt_wi)], uuid="t-twice")
        order = self._sync(dict(payload))
        order_again = self._sync(dict(payload))
        self.assertEqual(order, order_again)
        self.assertEqual(self.Job.search_count([("pos_order_id", "=", order.id)]), 1)
        # the job creation itself is idempotent per source
        self.assertEqual(order._earlydryer_create_job(), order.earlydryer_job_id)
        self.assertEqual(self.Job.search_count([("pos_order_id", "=", order.id)]), 1)

    @mute_logger("odoo.addons.earlydryer_pos.models.pos_order")
    def test_failed_job_keeps_the_sale_and_retries(self):
        original = PosOrder._earlydryer_create_job

        def boom(self):
            original(self)
            raise ValueError("printer on fire")

        with (
            trap_jobs() as trap,
            patch.object(PosOrder, "_earlydryer_create_job", boom),
        ):
            order = self._sync(self._payload([self._line(self.shirt_wi)]))
            trap.assert_jobs_count(1)
            self.assertEqual(
                trap.enqueued_jobs[0].method_name, "_earlydryer_create_job_from_pos"
            )
            self.assertEqual(trap.enqueued_jobs[0].recordset, order)
        self.assertEqual(order.state, "paid")
        self.assertTrue(order.payment_ids)
        self.assertIn("printer on fire", order.earlydryer_job_error)
        # the savepoint rolled back the half-created job
        self.assertFalse(order.earlydryer_job_id)
        self.assertFalse(self.Job.search([("pos_order_id", "=", order.id)]))
        activity_users = order.activity_ids.user_id
        self.assertIn(self.user_manager, activity_users)
        # the queued retry succeeds once the cause is gone
        trap.perform_enqueued_jobs()
        self.assertTrue(order.earlydryer_job_id)
        self.assertFalse(order.earlydryer_job_error)
        # and the button is harmless afterwards
        order.action_earlydryer_retry_job()
        self.assertEqual(self.Job.search_count([("pos_order_id", "=", order.id)]), 1)

    def test_refused_preprinted_tag_does_not_fail_the_job(self):
        line = self._line(self.shirt_wi, earlydryer_tag_codes="TT0101")
        first = self._sync(self._payload([line], config=self.config_2))
        self.assertEqual(first.earlydryer_job_id.item_ids.tag_code, "TT0101")
        # same physical tag scanned on another order while the first is open
        line = self._line(self.shirt_wi, qty=2, earlydryer_tag_codes="TT0101,TT0102")
        second = self._sync(self._payload([line], config=self.config_2))
        job = second.earlydryer_job_id
        self.assertTrue(job)
        self.assertFalse(second.earlydryer_job_error)
        conflict = job.item_ids.filtered("earlydryer_tag_conflict")
        self.assertEqual(len(conflict), 1)
        self.assertFalse(conflict.tag_code)
        self.assertIn("TT0101", conflict.earlydryer_tag_conflict)
        self.assertEqual((job.item_ids - conflict).tag_code, "TT0102")
        self.assertTrue(job.activity_ids)
        self.assertEqual(job.state, "received")
