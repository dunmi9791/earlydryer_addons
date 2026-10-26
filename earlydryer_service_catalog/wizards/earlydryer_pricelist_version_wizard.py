# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

DEFAULT_TZ = "Africa/Lagos"


class EarlydryerPricelistVersionWizard(models.TransientModel):
    """Annual price update: a new version of a price list from a date.

    The items valid on the effective date are copied with ``date_start`` =
    the effective date (00:00 local time) and the old items end one second
    before, i.e. on the day before. Past prices are never edited, so orders
    and invoices dated before the change keep their prices.
    """

    _name = "earlydryer.pricelist.version.wizard"
    _description = "Earlydryer Price List Version"

    pricelist_id = fields.Many2one("product.pricelist", required=True)
    effective_date = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self) + timedelta(days=1),
        help="First day of the new prices (local time). Must be in the future.",
    )
    percent_change = fields.Float(
        string="Change (%)",
        help="Applied to fixed prices, e.g. 10 for +10%, -5 for -5%. Items "
        "computed from another price list or a formula are copied as they are.",
    )
    rounding = fields.Float(
        digits="Product Price",
        help="Round the new fixed prices to a multiple of this amount, e.g. 50 "
        "for the nearest ₦50. 0 = currency rounding.",
    )
    item_count = fields.Integer(compute="_compute_item_count", string="Items to Copy")

    @api.depends("pricelist_id", "effective_date")
    def _compute_item_count(self):
        for wizard in self:
            wizard.item_count = (
                len(wizard._items_to_copy())
                if wizard.pricelist_id and wizard.effective_date
                else 0
            )

    @api.constrains("rounding")
    def _check_rounding(self):
        if any(wizard.rounding < 0 for wizard in self):
            raise ValidationError(self.env._("The rounding cannot be negative."))

    def _effective_datetime(self):
        """Effective date at 00:00 local time, as naive UTC."""
        self.ensure_one()
        tz = pytz.timezone(self.env.user.tz or DEFAULT_TZ)
        local = tz.localize(datetime.combine(self.effective_date, time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _items_to_copy(self):
        self.ensure_one()
        start = self._effective_datetime()
        return self.env["product.pricelist.item"].search(
            [
                ("pricelist_id", "=", self.pricelist_id.id),
                "|", ("date_start", "=", False), ("date_start", "<=", start),
                "|", ("date_end", "=", False), ("date_end", ">=", start),
            ]
        )  # fmt: skip

    def _new_price(self, price):
        self.ensure_one()
        price = price * (1 + self.percent_change / 100.0)
        if self.rounding:
            price = float_round(price, precision_rounding=self.rounding)
        return self.pricelist_id.currency_id.round(price)

    def _create_version(self):
        """Create the new items; return them."""
        self.ensure_one()
        if self.effective_date <= fields.Date.context_today(self):
            raise UserError(
                self.env._(
                    "The effective date must be in the future: past prices are "
                    "never changed."
                )
            )
        start = self._effective_datetime()
        later = self.env["product.pricelist.item"].search_count(
            [("pricelist_id", "=", self.pricelist_id.id), ("date_start", ">=", start)]
        )
        if later:
            raise UserError(
                self.env._(
                    "%(pricelist)s already has prices starting on or after this date.",
                    pricelist=self.pricelist_id.display_name,
                )
            )
        old_items = self._items_to_copy()
        if not old_items:
            raise UserError(
                self.env._("There are no prices valid on this date to copy.")
            )
        new_items = self.env["product.pricelist.item"]
        for item in old_items:
            default = {"date_start": start, "date_end": item.date_end}
            if item.compute_price == "fixed":
                default["fixed_price"] = self._new_price(item.fixed_price)
            new_items |= item.copy(default)
        old_items.write({"date_end": start - timedelta(seconds=1)})
        return new_items

    def action_create_version(self):
        new_items = self._create_version()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("New Prices"),
            "res_model": "product.pricelist.item",
            "view_mode": "list,form",
            "domain": [("id", "in", new_items.ids)],
        }
