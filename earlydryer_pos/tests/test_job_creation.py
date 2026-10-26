# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields
from odoo.tests import tagged

from .common import EarlydryerPosCommon


@tagged("post_install", "-at_install")
class TestJobCreation(EarlydryerPosCommon):
    def test_job_from_synced_order(self):
        codes = self._codes(4)
        date = self._hours_ago(5)
        shirt = self._line(
            self.shirt_wi,
            qty=2,
            uuid="t-shirt",
            discount=10.0,
            earlydryer_colour="White",
            earlydryer_condition_note="stain",
            earlydryer_tag_codes=",".join(codes[:2]),
        )
        suit = self._line(
            self.suit_dc,
            qty=1,
            uuid="t-suit",
            earlydryer_brand="Zara",
            earlydryer_tag_codes=",".join(codes[2:]),
        )
        beads = self._line(
            self.sur_beads.product_id,
            qty=1,
            earlydryer_parent_line_uuid="t-suit",
            earlydryer_surcharge_id=self.sur_beads.id,
        )
        express = self._line(
            self.express, qty=2, price=500, earlydryer_parent_line_uuid="t-shirt"
        )
        order = self._sync(
            self._payload(
                [shirt, suit, beads, express], date_order=date, earlydryer_express=True
            )
        )
        job = order.earlydryer_job_id
        self.assertTrue(job)
        self.assertEqual(self.Job.search_count([("pos_order_id", "=", order.id)]), 1)
        self.assertFalse(order.earlydryer_job_error)
        # 2 shirts x 1 piece + 1 suit x 2 pieces
        self.assertEqual(job.item_count, 4)
        self.assertTrue(job.express)
        self.assertEqual(job.channel, "walk_in")
        shirt_items = job.item_ids.filtered(lambda i: i.product_id == self.shirt_wi)
        self.assertEqual(shirt_items.mapped("price_unit"), [900.0, 900.0])
        self.assertEqual(set(shirt_items.mapped("colour")), {"White"})
        suit_items = job.item_ids.filtered(lambda i: i.product_id == self.suit_dc)
        self.assertEqual(suit_items.mapped("piece_index"), [1, 2])
        self.assertEqual(suit_items.surcharge_ids, self.sur_beads)
        self.assertEqual(suit_items.mapped("brand"), ["Zara", "Zara"])
        self.assertFalse(shirt_items.surcharge_ids)
        # linked lines resolved on the server
        beads_line = order.lines.filtered(
            lambda line: line.product_id == self.sur_beads.product_id
        )
        self.assertEqual(beads_line.earlydryer_parent_line_id.uuid, "t-suit")
        # tags written and consumed from the till's range
        self.assertEqual(sorted(job.item_ids.mapped("tag_code")), sorted(codes))
        tag_range = self.env["earlydryer.tag.range"].search(
            [("pos_config_id", "=", self.config.id)], limit=1
        )
        number = self.TagCode.number_for(codes[-1], self.branch_1)
        self.assertEqual(tag_range.next_number, number + 1)
        self.assertEqual(job.state, "tagged")
        # intake time is the order's, not the sync time
        self.assertEqual(job.received_on, fields.Datetime.to_datetime(date))
        self.assertEqual(job.received_on, order.date_order)

    def test_retail_only_order_has_no_job(self):
        retail = self.env["product.product"].create(
            {
                "name": "T Detergent",
                "type": "consu",
                "list_price": 2500,
                "available_in_pos": True,
            }
        )
        order = self._sync(
            self._payload([self._line(retail, price=2500)], partner=self.walk_in)
        )
        self.assertFalse(order.earlydryer_is_laundry)
        self.assertFalse(order.earlydryer_job_id)
        self.assertFalse(order.earlydryer_job_error)

    def test_offline_customer_created_on_sync(self):
        order = self._sync(
            self._payload(
                [self._line(self.shirt_wi)],
                partner=False,
                earlydryer_new_partner_name="T Offline Customer",
                earlydryer_new_partner_phone="+2348099990001",
            )
        )
        self.assertEqual(order.partner_id.name, "T Offline Customer")
        self.assertEqual(order.earlydryer_job_id.partner_id, order.partner_id)
        # same phone again: same contact
        order_2 = self._sync(
            self._payload(
                [self._line(self.shirt_wi)],
                partner=False,
                earlydryer_new_partner_name="Someone",
                earlydryer_new_partner_phone="+2348099990001",
            )
        )
        self.assertEqual(order_2.partner_id, order.partner_id)
