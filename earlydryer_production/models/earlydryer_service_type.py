# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

from .laundry_job_item import COLOUR_GROUPS


class EarlydryerServiceType(models.Model):
    _inherit = "earlydryer.service.type"

    default_colour_group = fields.Selection(
        COLOUR_GROUPS,
        help="Colour group proposed for the garments of this service at "
        "sorting (e.g. Special for dry cleaning). Empty: sorted by hand.",
    )
