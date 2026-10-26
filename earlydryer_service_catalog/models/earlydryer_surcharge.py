# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EarlydryerSurcharge(models.Model):
    """A charge on top of a garment line (silk, lace, beads, oversized...).

    A surcharge is always invoiced as its own order line, on its own product,
    linked to the garment line by the order modules. It never changes the
    garment line price.
    """

    _name = "earlydryer.surcharge"
    _description = "Earlydryer Surcharge"
    _order = "sequence, name"
    _rec_names_search = ["name", "code"]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, size=10)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    kind = fields.Selection(
        [
            ("fabric", "Fabric"),
            ("size", "Size"),
            ("embellishment", "Embellishment"),
            ("stain", "Stain"),
            ("other", "Other"),
        ],
        required=True,
        default="other",
    )
    compute_mode = fields.Selection(
        [("fixed", "Fixed Amount"), ("percent", "Percentage of Garment Price")],
        required=True,
        default="fixed",
        help="Fixed: the price of the surcharge product in the applicable "
        "price list. Percentage: a percentage of the garment line unit price.",
    )
    percent = fields.Float(help="Percentage of the garment unit price.")
    product_id = fields.Many2one(
        "product.product",
        # not required in the UI: created on save when empty (see create)
        ondelete="restrict",
        domain=[("earlydryer_kind", "=", "surcharge")],
        help="Product of the surcharge order line. Created automatically when "
        "left empty.",
    )
    amount = fields.Float(
        related="product_id.list_price",
        readonly=False,
        string="Default Amount",
        help="Sales price of the surcharge product, used when no price list "
        "item overrides it (fixed mode only).",
    )
    currency_id = fields.Many2one(related="product_id.currency_id")
    service_type_ids = fields.Many2many(
        "earlydryer.service.type",
        "earlydryer_surcharge_service_type_rel",
        "surcharge_id",
        "service_type_id",
        string="Service Types",
        help="Leave empty to apply to every service type.",
    )
    category_ids = fields.Many2many(
        "earlydryer.garment.category",
        "earlydryer_surcharge_category_rel",
        "surcharge_id",
        "category_id",
        string="Garment Categories",
        help="Leave empty to apply to every garment category.",
    )

    _code_uniq = models.Constraint("unique(code)", "The surcharge code must be unique.")

    @api.constrains("compute_mode", "percent")
    def _check_percent(self):
        for surcharge in self:
            if surcharge.compute_mode == "percent" and surcharge.percent <= 0:
                raise ValidationError(
                    self.env._(
                        "%(surcharge)s: a percentage surcharge needs a positive "
                        "percentage.",
                        surcharge=surcharge.display_name,
                    )
                )

    @api.constrains("product_id")
    def _check_product_kind(self):
        for surcharge in self:
            if (
                not surcharge.product_id
                or surcharge.product_id.earlydryer_kind != "surcharge"
            ):
                raise ValidationError(
                    self.env._(
                        "%(surcharge)s: the product must be an Earlydryer "
                        "surcharge product.",
                        surcharge=surcharge.display_name,
                    )
                )

    @api.model
    def _prepare_product_vals(self, vals):
        code = vals["code"]
        return {
            "name": vals["name"],
            "default_code": f"SUR-{code}",
            "list_price": vals.get("amount", 0.0),
            "taxes_id": [fields.Command.clear()],
            **self.env["product.template"]._earlydryer_service_product_vals(
                "surcharge",
                self.env.ref(
                    "earlydryer_service_catalog.pos_category_extras",
                    raise_if_not_found=False,
                ),
            ),
        }

    @api.model_create_multi
    def create(self, vals_list):
        Product = self.env["product.product"]
        for vals in vals_list:
            if vals.get("code"):
                vals["code"] = vals["code"].strip().upper()
            if not vals.get("product_id") and vals.get("name") and vals.get("code"):
                product = Product.create(self._prepare_product_vals(vals))
                vals["product_id"] = product.id
                vals.pop("amount", None)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("code"):
            vals = dict(vals, code=vals["code"].strip().upper())
        return super().write(vals)

    def _is_applicable(self, category, service_type):
        """Whether this surcharge applies to a ``category`` × ``service_type`` item."""
        self.ensure_one()
        return (not self.category_ids or category in self.category_ids) and (
            not self.service_type_ids or service_type in self.service_type_ids
        )
