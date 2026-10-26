# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TestJobCreation(LaundryJobCommon):
    def test_sale_confirmation_creates_job(self):
        sale = self._create_sale(
            [(self.shirt_wi, 2, self.sur_beads), (self.suit_dc, 1, None)],
            express=True,
        )
        sale.action_earlydryer_apply_extras()
        shirt_line = sale.order_line.filtered(
            lambda line: line.product_id == self.shirt_wi
        )
        extras = shirt_line.earlydryer_child_line_ids
        # beads (fixed 500 in the plant's walk-in list) and express (50% of 1000)
        self.assertEqual(len(extras), 2)
        self.assertEqual(
            sorted(extras.mapped("price_unit")), [500.0, 500.0], extras.mapped("name")
        )
        self.assertEqual(shirt_line.price_unit, 1000.0)
        sale.action_confirm()

        job = sale.laundry_job_ids
        self.assertEqual(len(job), 1)
        self.assertEqual(job.earlydryer_branch_id, self.branch_1)
        self.assertEqual(job.partner_id, self.partner)
        self.assertTrue(job.express)
        self.assertEqual(job.state, "received")
        # 2 shirts x 1 piece + 1 suit x 2 pieces
        self.assertEqual(job.item_count, 4)
        shirts = job.item_ids.filtered(lambda i: i.product_id == self.shirt_wi)
        self.assertEqual(shirts.mapped("price_unit"), [1000.0, 1000.0])
        self.assertEqual(shirts.surcharge_ids, self.sur_beads)
        self.assertEqual(shirts.sale_line_id, shirt_line)
        suit = job.item_ids.filtered(lambda i: i.product_id == self.suit_dc)
        self.assertEqual(suit.mapped("piece_index"), [1, 2])
        self.assertEqual(suit.mapped("price_unit"), [100.0, 0.0])
        # amount of the order: garments, surcharges and express
        self.assertAlmostEqual(job.amount_total, sale.amount_total)
        self.assertEqual(len(job.stage_log_ids), 1)

        # confirming again (or re-running the hook) does not duplicate
        sale._earlydryer_create_laundry_jobs()
        self.assertEqual(self.Job.search_count([("sale_order_id", "=", sale.id)]), 1)

    def test_non_laundry_order_has_no_job(self):
        sale = self._create_sale([(self.sur_beads.product_id, 1, None)])
        sale.earlydryer_branch_id = False
        sale.action_confirm()
        self.assertFalse(sale.laundry_job_ids)

    def test_branch_required_on_laundry_order(self):
        sale = self._create_sale([(self.shirt_wi, 1, None)])
        sale.earlydryer_branch_id = False
        with self.assertRaises(UserError):
            sale.action_confirm()

    def test_create_from_lines_without_sale(self):
        lines = [
            {
                "product_id": self.suit_dc.id,
                "quantity": 2,
                "price_unit": 3000.0,
                "surcharge_ids": self.sur_beads.ids,
                "colour": "Black",
                "condition_note": "Missing button",
            }
        ]
        job = self.Job.with_user(self.user_manager)._earlydryer_create_from_lines(
            self.partner, self.branch_1, "phone", "deliver", False, lines
        )
        self.assertEqual(job.item_count, 4)
        self.assertFalse(job.sale_order_id or job.pos_order_id)
        self.assertEqual(job.channel, "phone")
        self.assertEqual(set(job.item_ids.mapped("colour")), {"Black"})
        self.assertEqual(sum(job.item_ids.mapped("price_unit")), 6000.0)
        self.assertEqual(job.amount_due, 0.0)
        # a manual job is for Branch Managers only
        with self.assertRaises(AccessError):
            self.Job.with_user(self.user_front_desk)._earlydryer_create_from_lines(
                self.partner, self.branch_1, "phone", "deliver", False, lines
            )

    def test_create_from_lines_idempotent_per_source(self):
        sale = self._create_sale([(self.shirt_wi, 1, None)])
        sale.action_confirm()
        job = sale.laundry_job_ids
        again = self.Job._earlydryer_create_from_lines(
            self.partner,
            self.branch_1,
            "walk_in",
            "collect",
            False,
            [{"product_id": self.shirt_wi.id, "quantity": 3}],
            source=sale,
        )
        self.assertEqual(again, job)
        self.assertEqual(job.item_count, 1)

    def test_source_branch_must_match(self):
        job = self._create_job()
        with self.assertRaises(UserError):
            job.earlydryer_branch_id = self.branch_2

    def test_cancel_posts_on_source(self):
        job = self._create_job()
        sale = job.sale_order_id
        with self.assertRaises(AccessError):
            job.with_user(self.user_front_desk).action_move_to(
                "cancelled", note="Customer changed mind"
            )
        job.with_user(self.user_manager).action_move_to(
            "cancelled", note="Customer changed mind"
        )
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(job.cancel_reason, "Customer changed mind")
        self.assertTrue(job.closed_on)
        self.assertEqual(sale.state, "sale")
        self.assertIn("was cancelled", sale.message_ids[0].body)
