# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

# job state -> service type flag telling whether the service needs that stage
SKIPPABLE_STAGES = {
    "washed": "uses_wash",
    "dried": "uses_dry",
    "ironed": "uses_iron",
}


class EarlydryerServiceType(models.Model):
    _inherit = "earlydryer.service.type"

    # Three flags rather than a many2many to a stage model: only these three
    # production stages can be left out, and booleans are simpler to set up,
    # to read in the stage-move code and to load in the offline POS.
    uses_wash = fields.Boolean(
        string="Washing Stage",
        default=True,
        help="Items of this service go through the Washed stage.",
    )
    uses_dry = fields.Boolean(
        string="Drying Stage",
        default=True,
        help="Items of this service go through the Dried stage.",
    )
    uses_iron = fields.Boolean(
        string="Ironing Stage",
        default=True,
        help="Items of this service go through the Ironed stage.",
    )

    def _uses_stage(self, state):
        """Whether every service of ``self`` needs ``state`` (True for
        non-skippable stages)."""
        fname = SKIPPABLE_STAGES.get(state)
        if not fname:
            return True
        return any(service[fname] for service in self)
