# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    # set by the till (patch of earlydryer_pos's intake) when the order was
    # opened from "Price in POS" of a pickup; the job created at sync links
    # back to the pickup (laundry.job._earlydryer_create_from_lines)
    earlydryer_pickup_stop_id = fields.Many2one(
        "earlydryer.logistics.stop",
        string="Pickup",
        copy=False,
        index="btree_not_null",
    )
