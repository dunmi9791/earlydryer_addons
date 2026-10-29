# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    earlydryer_pickup_stop_id = fields.Many2one(
        "earlydryer.logistics.stop",
        string="Pickup",
        copy=False,
        index="btree_not_null",
        domain=[("stop_type", "=", "pickup")],
        help="Pickup whose bags this order prices.",
    )
