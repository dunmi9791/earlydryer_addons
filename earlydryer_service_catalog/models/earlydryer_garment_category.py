# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

GARMENT_GROUPS = [
    ("tops", "Tops"),
    ("bottoms", "Bottoms"),
    ("traditional", "Traditional"),
    ("suits_outerwear", "Suits & Outerwear"),
    ("dresses", "Dresses"),
    ("accessories", "Accessories"),
    ("household", "Household"),
    ("footwear", "Footwear"),
    ("bags_luggage", "Bags & Luggage"),
    ("other", "Other"),
]


class EarlydryerGarmentCategory(models.Model):
    _name = "earlydryer.garment.category"
    _description = "Earlydryer Garment Category"
    _order = "sequence, name"
    _rec_names_search = ["name", "code"]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        size=10,
        help="Short, stable upper-case code, used in product codes (e.g. SHIRT-WI).",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    # "group" is an SQL keyword, hence the prefix
    garment_group = fields.Selection(
        GARMENT_GROUPS, string="Group", required=True, default="other"
    )
    piece_count = fields.Integer(
        default=1,
        help="Number of pieces of one item (a 3-piece suit counts as 3 and "
        "gets 3 tags).",
    )
    average_weight_kg = fields.Float(
        string="Average Weight (kg)",
        digits=(16, 3),
        help="Optional. Used later to estimate the cost per kg.",
    )
    image_128 = fields.Image(max_width=128, max_height=128)
    note = fields.Text()
    product_tmpl_ids = fields.One2many(
        "product.template", "earlydryer_garment_category_id", string="Products"
    )
    product_count = fields.Integer(compute="_compute_product_count")

    _code_uniq = models.Constraint(
        "unique(code)", "The garment category code must be unique."
    )
    _piece_count_positive = models.Constraint(
        "CHECK(piece_count >= 1)", "A garment has at least one piece."
    )

    @api.depends("name", "code")
    def _compute_display_name(self):
        for category in self:
            category.display_name = category.name or category.code

    def _compute_product_count(self):
        data = self.env["product.template"]._read_group(
            [("earlydryer_garment_category_id", "in", self.ids)],
            ["earlydryer_garment_category_id"],
            ["__count"],
        )
        counts = {category.id: count for category, count in data}
        for category in self:
            category.product_count = counts.get(category.id, 0)

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

    def action_view_products(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_service_catalog.product_template_action_laundry"
        )
        action["domain"] = [("earlydryer_garment_category_id", "=", self.id)]
        action["context"] = {
            "default_earlydryer_kind": "laundry",
            "default_earlydryer_garment_category_id": self.id,
        }
        return action
