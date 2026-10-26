# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import EarlydryerPosCommon

# 1x1 JPEG
PHOTO = base64.b64encode(
    bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c"
        "140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27"
        "393d38323c2e333432ffc0000b080001000101011100ffc4001f000001050101010101010000000000"
        "0000000102030405060708090a0bffda0008010100003f00d2cf20ffd9"
    )
).decode()


@tagged("post_install", "-at_install")
class TestPhotosSecurity(EarlydryerPosCommon):
    def test_photo_upload(self):
        order = self._sync(
            self._payload(
                [
                    self._line(
                        self.suit_dc, uuid="t-photo-line", earlydryer_photo_count=1
                    )
                ]
            )
        )
        Order = self.Order.with_user(self.user_front_desk)
        result = Order.earlydryer_upload_photo(order.uuid, "t-photo-line", 0, PHOTO)
        self.assertEqual(result["status"], "done")
        items = order.earlydryer_job_id.item_ids
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item.photo_ids.id, result["attachment_id"])
        # retried upload: same attachment, nothing added
        again = Order.earlydryer_upload_photo(order.uuid, "t-photo-line", 0, PHOTO)
        self.assertEqual(again["attachment_id"], result["attachment_id"])
        self.assertEqual(len(items.photo_ids), 1)
        # order not synced yet: the till keeps the photo and retries
        pending = Order.earlydryer_upload_photo("t-unknown", "x", 0, PHOTO)
        self.assertEqual(pending["status"], "pending")
        # a Front Desk user of another plant is refused
        with self.assertRaises(AccessError):
            self.Order.with_user(self.user_front_desk_2).earlydryer_upload_photo(
                order.uuid, "t-photo-line", 1, PHOTO
            )

    def test_config_of_other_branch_invisible(self):
        Config = self.env["pos.config"].with_user(self.user_front_desk)
        visible = Config.search([("id", "in", (self.config | self.config_2).ids)])
        self.assertEqual(visible, self.config)
        with self.assertRaises(AccessError):
            self.config_2.with_user(self.user_front_desk).earlydryer_pos_refresh()
