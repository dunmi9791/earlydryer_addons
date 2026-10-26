# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EarlydryerArea(models.Model):
    """A named area of a city (Wuse II, Gwarinpa, Lugbe...).

    OCA ``base_location`` 19.0 knows cities (``res.city``) and postal codes
    (``res.city.zip``, ``name`` = the code, required). Abuja areas are not
    postal codes: several areas share one code and addresses are given by area
    and landmark, so an area needs its own record, linked to its city, with an
    optional centre point for distance estimates.
    """

    _name = "earlydryer.area"
    _description = "Earlydryer Area"
    _order = "city_id, name"
    _rec_names_search = ["name", "code"]

    name = fields.Char(required=True, translate=False)
    code = fields.Char(help="Short code used on route sheets.")
    city_id = fields.Many2one(
        "res.city",
        string="City",
        ondelete="restrict",
        index=True,
        help="base_location city the area belongs to.",
    )
    zip_id = fields.Many2one(
        "res.city.zip",
        string="Postal Code",
        domain="[('city_id', '=', city_id)]",
        help="Optional base_location postal code of the area.",
    )
    latitude = fields.Float(digits=(10, 7), help="Centre point of the area.")
    longitude = fields.Float(digits=(10, 7))
    has_centre = fields.Boolean(compute="_compute_has_centre")
    active = fields.Boolean(default=True)
    zone_ids = fields.Many2many(
        "earlydryer.delivery.zone",
        "earlydryer_delivery_zone_area_rel",
        "area_id",
        "zone_id",
        string="Zones",
        readonly=True,
    )
    note = fields.Text()

    _name_city_uniq = models.Constraint(
        "unique(name, city_id)", "An area name must be unique per city."
    )

    @api.depends("latitude", "longitude")
    def _compute_has_centre(self):
        for area in self:
            area.has_centre = bool(area.latitude or area.longitude)

    @api.constrains("latitude", "longitude")
    def _check_coordinates(self):
        for area in self:
            if not -90 <= area.latitude <= 90 or not -180 <= area.longitude <= 180:
                raise ValidationError(
                    self.env._("Invalid centre point for area %(area)s.", area=area.name)
                )
