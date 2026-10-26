# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # coordinates: core partner_latitude / partner_longitude (base, 19.0);
    # captured by riders, never geocoded through a paid API
    earlydryer_area_id = fields.Many2one(
        "earlydryer.area", string="Area", index="btree_not_null"
    )
    earlydryer_landmark = fields.Char(
        string="Landmark", help='e.g. "opposite Jabi Lake Mall, blue gate".'
    )
    earlydryer_gate_instructions = fields.Char(string="Gate Instructions")
    earlydryer_gps_accuracy_m = fields.Float(string="GPS Accuracy (m)")
    earlydryer_gps_captured_on = fields.Datetime(string="GPS Captured On")
    earlydryer_map_url = fields.Char(string="Map", compute="_compute_earlydryer_map_url")
    earlydryer_cod_blocked = fields.Boolean(
        string="No Cash on Delivery",
        help="Deliveries of this customer must be paid (or on approved credit) "
        "before they leave the plant.",
    )
    earlydryer_is_carrier = fields.Boolean(
        string="3PL Carrier", help="Logistics company that can run delivery trips."
    )

    @api.depends(
        "partner_latitude", "partner_longitude", "street", "city", "earlydryer_area_id"
    )
    def _compute_earlydryer_map_url(self):
        Stop = self.env["earlydryer.logistics.stop"]
        for partner in self:
            text = ", ".join(
                filter(
                    None,
                    [
                        partner.street,
                        partner.earlydryer_area_id.name,
                        partner.city,
                        partner.country_id.name,
                    ],
                )
            )
            partner.earlydryer_map_url = Stop._earlydryer_map_url(
                partner.partner_latitude, partner.partner_longitude, text
            )

    def action_earlydryer_open_map(self):
        self.ensure_one()
        if not self.earlydryer_map_url:
            return False
        return {"type": "ir.actions.act_url", "url": self.earlydryer_map_url, "target": "new"}
