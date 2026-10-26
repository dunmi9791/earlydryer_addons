# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

from odoo.addons.earlydryer_laundry_order.models.laundry_job import (
    REWORK_STATES,
    STATES,
)


class EarlydryerReworkReason(models.Model):
    _name = "earlydryer.rework.reason"
    _description = "Earlydryer QC Rework Reason"
    _order = "sequence, name"
    _rec_names_search = ["name", "code"]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, size=16)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    default_return_state = fields.Selection(
        [(state, label) for state, label in STATES if state in REWORK_STATES],
        string="Send Back To",
        required=True,
        default="washed",
    )
    is_damage = fields.Boolean(
        string="Damage",
        help="The garment is damaged: the branch manager is alerted and a "
        "claim can be opened.",
    )

    _code_uniq = models.Constraint(
        "unique(code)", "The rework reason code must be unique."
    )

    @api.model
    def _normalize_vals(self, vals):
        if vals.get("code"):
            vals["code"] = vals["code"].strip().upper()
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_vals(dict(v)) for v in vals_list])

    def write(self, vals):
        return super().write(self._normalize_vals(dict(vals)))
