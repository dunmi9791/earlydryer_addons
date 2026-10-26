# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError

PLACEHOLDER_HELP = (
    " The values shipped with the module are placeholders until Earlydryer "
    "confirms its turnaround times and express surcharges."
)


class EarlydryerServiceType(models.Model):
    _name = "earlydryer.service.type"
    _description = "Earlydryer Service Type"
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
    description = fields.Text(translate=True)
    standard_turnaround_hours = fields.Integer(
        required=True,
        default=72,
        help="Working hours of the plant between drop-off and ready for "
        "collection." + PLACEHOLDER_HELP,
    )
    express_available = fields.Boolean(
        help="Express can be sold for this service." + PLACEHOLDER_HELP
    )
    express_turnaround_hours = fields.Integer(
        help="Working hours for express; must be less than the standard "
        "turnaround." + PLACEHOLDER_HELP,
    )
    express_surcharge_kind = fields.Selection(
        [("percent", "Percentage"), ("fixed", "Fixed Amount")],
        default="percent",
        help="Percentage: of the garment unit price. Fixed: an amount in the "
        "company currency per item." + PLACEHOLDER_HELP,
    )
    express_surcharge_value = fields.Float(
        help="Percentage or amount of the express charge." + PLACEHOLDER_HELP
    )
    requires_tag = fields.Boolean(
        default=True,
        help="Each item gets an individual garment tag at intake.",
    )
    allowed_category_ids = fields.Many2many(
        "earlydryer.garment.category",
        "earlydryer_service_type_category_rel",
        "service_type_id",
        "category_id",
        string="Allowed Garment Categories",
        help="Leave empty to allow every category.",
    )
    pos_category_id = fields.Many2one(
        "pos.category",
        string="POS Category",
        help="Created by the catalogue generator when empty.",
    )
    product_tmpl_ids = fields.One2many(
        "product.template", "earlydryer_service_type_id", string="Products"
    )
    product_count = fields.Integer(compute="_compute_product_count")

    _code_uniq = models.Constraint(
        "unique(code)", "The service type code must be unique."
    )
    _standard_positive = models.Constraint(
        "CHECK(standard_turnaround_hours > 0)",
        "The standard turnaround must be positive.",
    )

    @api.constrains(
        "express_available", "express_turnaround_hours", "standard_turnaround_hours"
    )
    def _check_express(self):
        for service in self.filtered("express_available"):
            if service.express_turnaround_hours <= 0:
                raise ValidationError(
                    self.env._(
                        "%(service)s: set the express turnaround hours.",
                        service=service.display_name,
                    )
                )
            if service.express_turnaround_hours >= service.standard_turnaround_hours:
                raise ValidationError(
                    self.env._(
                        "%(service)s: the express turnaround must be shorter "
                        "than the standard turnaround.",
                        service=service.display_name,
                    )
                )

    @api.constrains("express_surcharge_value")
    def _check_express_value(self):
        if any(service.express_surcharge_value < 0 for service in self):
            raise ValidationError(
                self.env._("The express surcharge cannot be negative.")
            )

    def _compute_product_count(self):
        data = self.env["product.template"]._read_group(
            [("earlydryer_service_type_id", "in", self.ids)],
            ["earlydryer_service_type_id"],
            ["__count"],
        )
        counts = {service.id: count for service, count in data}
        for service in self:
            service.product_count = counts.get(service.id, 0)

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

    def _allows_category(self, category):
        """Whether this service can be sold for ``category``."""
        self.ensure_one()
        return not self.allowed_category_ids or category in self.allowed_category_ids

    def _turnaround_hours(self, express=False):
        """Turnaround in working hours (express when requested and available)."""
        self.ensure_one()
        if express and self.express_available:
            return self.express_turnaround_hours
        return self.standard_turnaround_hours

    def _ensure_pos_category(self):
        """Return the POS category of each service, creating missing ones."""
        PosCategory = self.env["pos.category"]
        parent = self.env.ref(
            "earlydryer_service_catalog.pos_category_laundry", raise_if_not_found=False
        )
        for service in self.filtered(lambda s: not s.pos_category_id):
            service.pos_category_id = PosCategory.create(
                {
                    "name": service.name,
                    "parent_id": parent.id if parent else False,
                    "sequence": service.sequence,
                }
            )
        return self.pos_category_id

    def action_view_products(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_service_catalog.product_template_action_laundry"
        )
        action["domain"] = [("earlydryer_service_type_id", "=", self.id)]
        action["context"] = {
            "default_earlydryer_kind": "laundry",
            "default_earlydryer_service_type_id": self.id,
        }
        return action
