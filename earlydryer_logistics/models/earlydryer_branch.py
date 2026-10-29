# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerBranch(models.Model):
    _inherit = "earlydryer.branch"

    earlydryer_auto_draft_delivery = fields.Boolean(
        string="Auto Draft Deliveries",
        help="When a job to deliver becomes Ready without a delivery, create a "
        "draft delivery stop (otherwise: an activity for Operations).",
    )
    earlydryer_allow_cod = fields.Boolean(
        string="Allow Cash on Delivery",
        default=True,
        help="Riders may collect the balance at the door.",
    )
    earlydryer_failed_fee_mode = fields.Selection(
        [
            ("none", "None"),
            ("flat", "Flat Amount"),
            ("same_as_delivery", "Same as the Delivery Fee"),
        ],
        string="Failed Delivery Fee",
        default="none",
        required=True,
        help="PLACEHOLDER until Earlydryer decides: charged on the next attempt "
        "when the failure reason says a fee applies.",
    )
    earlydryer_failed_fee_amount = fields.Monetary(
        string="Failed Fee Amount", currency_field="currency_id"
    )
    earlydryer_stop_sequence_id = fields.Many2one(
        "ir.sequence", string="Stop Sequence", readonly=True, copy=False
    )
    earlydryer_trip_sequence_id = fields.Many2one(
        "ir.sequence", string="Trip Sequence", readonly=True, copy=False
    )
    earlydryer_zone_ids = fields.One2many(
        "earlydryer.delivery.zone", "earlydryer_branch_id", string="Delivery Zones"
    )

    def _earlydryer_logistics_ensure_sequences(self):
        """``{"stop": seq, "trip": seq}`` of the (single) branch, created on
        first use: ``<CODE>/STP/00001`` and ``<CODE>/TRP/0001``."""
        Sequence = self.env["ir.sequence"].sudo()
        for branch in self.sudo():
            if not branch.earlydryer_stop_sequence_id:
                branch.earlydryer_stop_sequence_id = Sequence.create(
                    {
                        "name": self.env._("Stops %s", branch.display_name),
                        "code": f"earlydryer.logistics.stop.{branch.id}",
                        "prefix": f"{branch.code}/STP/",
                        "padding": 5,
                        "company_id": branch.company_id.id,
                    }
                )
            if not branch.earlydryer_trip_sequence_id:
                branch.earlydryer_trip_sequence_id = Sequence.create(
                    {
                        "name": self.env._("Trips %s", branch.display_name),
                        "code": f"earlydryer.logistics.trip.{branch.id}",
                        "prefix": f"{branch.code}/TRP/",
                        "padding": 4,
                        "company_id": branch.company_id.id,
                    }
                )
        branch = self[:1].sudo()
        return {
            "stop": branch.earlydryer_stop_sequence_id,
            "trip": branch.earlydryer_trip_sequence_id,
        }

    def write(self, vals):
        res = super().write(vals)
        if "code" in vals:
            for branch in self.sudo():
                if branch.earlydryer_stop_sequence_id:
                    branch.earlydryer_stop_sequence_id.prefix = f"{branch.code}/STP/"
                if branch.earlydryer_trip_sequence_id:
                    branch.earlydryer_trip_sequence_id.prefix = f"{branch.code}/TRP/"
        return res
