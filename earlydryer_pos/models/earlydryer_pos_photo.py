# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models
from odoo.fields import Command


class EarlydryerPosPhoto(models.Model):
    """A condition photo uploaded by a till: one per (order, line, index), so
    a retried upload never attaches the photo twice."""

    _name = "earlydryer.pos.photo"
    _description = "Earlydryer POS Condition Photo"
    _order = "id desc"

    order_uuid = fields.Char(required=True, index=True, readonly=True)
    line_uuid = fields.Char(required=True, readonly=True)
    index = fields.Integer(required=True, readonly=True)
    pos_order_id = fields.Many2one(
        "pos.order", required=True, index=True, ondelete="cascade", readonly=True
    )
    pos_line_id = fields.Many2one("pos.order.line", ondelete="set null", readonly=True)
    earlydryer_branch_id = fields.Many2one(
        related="pos_order_id.config_id.earlydryer_branch_id", store=True, index=True
    )
    attachment_id = fields.Many2one(
        "ir.attachment", required=True, ondelete="cascade", readonly=True
    )

    _photo_uniq = models.Constraint(
        "unique(order_uuid, line_uuid, index)",
        "This photo was already uploaded.",
    )

    def _earlydryer_attach_to_items(self):
        """Add the photo to every item of its garment line."""
        Item = self.env["laundry.job.item"].sudo()
        for photo in self.sudo():
            items = Item.search([("pos_line_id", "=", photo.pos_line_id.id)])
            missing = items.filtered(
                lambda item, photo=photo: photo.attachment_id not in item.photo_ids
            )
            if missing:
                missing.write({"photo_ids": [Command.link(photo.attachment_id.id)]})
        return True
