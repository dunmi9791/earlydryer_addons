# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EarlydryerDeliveryZone(models.Model):
    """Areas served by a plant, with the fee told to the customer."""

    _name = "earlydryer.delivery.zone"
    _description = "Earlydryer Delivery Zone"
    _inherit = ["mail.thread", "earlydryer.branch.mixin"]
    _order = "earlydryer_branch_id, sequence, name"

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(
        default=10, help="Default route order of the zone when GPS is missing."
    )
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        related="earlydryer_branch_id.company_id", store=True, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    area_ids = fields.Many2many(
        "earlydryer.area",
        "earlydryer_delivery_zone_area_rel",
        "zone_id",
        "area_id",
        string="Areas",
    )
    fee_mode = fields.Selection(
        [("flat", "Flat Fee"), ("distance", "By Distance")],
        required=True,
        default="flat",
        tracking=True,
    )
    flat_fee = fields.Monetary(tracking=True)
    base_fee = fields.Monetary(tracking=True, help="Distance mode: fixed part.")
    fee_per_km = fields.Monetary(string="Fee per km", tracking=True)
    max_km = fields.Float(
        string="Max km",
        tracking=True,
        help="Distance mode: addresses further than this are not served (0 = "
        "no limit).",
    )
    pickup_fee = fields.Monetary(
        tracking=True, help="Fee of a pickup in this zone (default 0: free)."
    )
    express_fee = fields.Monetary(
        tracking=True,
        help="Added on top of the delivery fee for same-day / express delivery.",
    )
    free_over_amount = fields.Monetary(
        string="Free Delivery Over",
        tracking=True,
        help="Order value from which the delivery fee is waived (0 = never "
        "free). The express fee still applies.",
    )
    min_order_amount = fields.Monetary(
        string="Minimum Order",
        tracking=True,
        help="No delivery below this order value unless a Branch Manager "
        "approves.",
    )
    note = fields.Text()

    @api.constrains("area_ids", "earlydryer_branch_id", "active")
    def _check_area_unique_per_branch(self):
        for zone in self.filtered("active"):
            others = self.search(
                [
                    ("id", "!=", zone.id),
                    ("earlydryer_branch_id", "=", zone.earlydryer_branch_id.id),
                    ("area_ids", "in", zone.area_ids.ids),
                ]
            )
            if others:
                shared = zone.area_ids & others.area_ids
                raise ValidationError(
                    self.env._(
                        "Area %(area)s already belongs to zone %(zone)s of this "
                        "plant: an area belongs to at most one zone per plant.",
                        area=", ".join(shared.mapped("name")),
                        zone=others[:1].name,
                    )
                )

    @api.constrains(
        "flat_fee",
        "base_fee",
        "fee_per_km",
        "max_km",
        "pickup_fee",
        "express_fee",
        "free_over_amount",
        "min_order_amount",
    )
    def _check_amounts(self):
        for zone in self:
            values = [
                zone.flat_fee,
                zone.base_fee,
                zone.fee_per_km,
                zone.max_km,
                zone.pickup_fee,
                zone.express_fee,
                zone.free_over_amount,
                zone.min_order_amount,
            ]
            if any(value < 0 for value in values):
                raise ValidationError(self.env._("Zone fees cannot be negative."))

    @api.model
    def _earlydryer_find(self, branch, area):
        """Active zone of ``branch`` containing ``area`` (or empty)."""
        if not branch or not area:
            return self.browse()
        return self.search(
            [
                ("earlydryer_branch_id", "=", branch.id),
                ("area_ids", "in", area.ids),
            ],
            limit=1,
        )
