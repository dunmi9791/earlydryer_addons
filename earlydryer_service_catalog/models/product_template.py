# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError

EARLYDRYER_KINDS = [
    ("laundry", "Laundry Service"),
    ("surcharge", "Surcharge"),
    ("express", "Express"),
    ("retail", "Retail Product"),
]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    earlydryer_kind = fields.Selection(
        EARLYDRYER_KINDS,
        index=True,
        help="Laundry: a garment category × service type item. Surcharge and "
        "Express: charges invoiced as their own line next to a garment line. "
        "Retail: goods sold from stock (detergent, hangers...).",
    )
    earlydryer_garment_category_id = fields.Many2one(
        "earlydryer.garment.category",
        string="Garment Category",
        index=True,
        ondelete="restrict",
    )
    earlydryer_service_type_id = fields.Many2one(
        "earlydryer.service.type",
        string="Service Type",
        index=True,
        ondelete="restrict",
    )
    earlydryer_turnaround_hours_override = fields.Integer(
        string="Turnaround Override (h)",
        help="Leave 0 to use the turnaround of the service type.",
    )
    earlydryer_express_turnaround_hours_override = fields.Integer(
        string="Express Turnaround Override (h)",
        help="Leave 0 to use the express turnaround of the service type.",
    )
    earlydryer_turnaround_hours = fields.Integer(
        string="Turnaround (h)",
        compute="_compute_earlydryer_turnaround_hours",
        store=True,
        aggregator=None,
        help="Working hours of the plant between drop-off and ready.",
    )
    earlydryer_express_turnaround_hours = fields.Integer(
        string="Express Turnaround (h)",
        compute="_compute_earlydryer_turnaround_hours",
        store=True,
        aggregator=None,
    )
    earlydryer_express_available = fields.Boolean(
        related="earlydryer_service_type_id.express_available",
        string="Express Available",
    )

    _earlydryer_laundry_uniq = models.UniqueIndex(
        "(earlydryer_garment_category_id, earlydryer_service_type_id, "
        "COALESCE(company_id, 0)) WHERE active AND earlydryer_kind = 'laundry'",
        "There is already an active laundry product for this garment category "
        "and service type.",
    )

    @api.depends(
        "earlydryer_kind",
        "earlydryer_service_type_id.standard_turnaround_hours",
        "earlydryer_service_type_id.express_turnaround_hours",
        "earlydryer_service_type_id.express_available",
        "earlydryer_turnaround_hours_override",
        "earlydryer_express_turnaround_hours_override",
    )
    def _compute_earlydryer_turnaround_hours(self):
        for product in self:
            service = product.earlydryer_service_type_id
            if product.earlydryer_kind != "laundry" or not service:
                product.earlydryer_turnaround_hours = 0
                product.earlydryer_express_turnaround_hours = 0
                continue
            product.earlydryer_turnaround_hours = (
                product.earlydryer_turnaround_hours_override
                or service.standard_turnaround_hours
            )
            product.earlydryer_express_turnaround_hours = (
                (
                    product.earlydryer_express_turnaround_hours_override
                    or service.express_turnaround_hours
                )
                if service.express_available
                else 0
            )

    @api.constrains(
        "earlydryer_kind",
        "earlydryer_garment_category_id",
        "earlydryer_service_type_id",
    )
    def _check_earlydryer_laundry(self):
        for product in self.filtered(lambda p: p.earlydryer_kind == "laundry"):
            if (
                not product.earlydryer_garment_category_id
                or not product.earlydryer_service_type_id
            ):
                raise ValidationError(
                    self.env._(
                        "%(product)s: a laundry product needs a garment category "
                        "and a service type.",
                        product=product.display_name,
                    )
                )
            if product.type != "service":
                raise ValidationError(
                    self.env._(
                        "%(product)s: a laundry product must be a service.",
                        product=product.display_name,
                    )
                )

    @api.model
    def _earlydryer_service_product_vals(self, kind, pos_category=None):
        """Common values of laundry, surcharge and express products."""
        vals = {
            "earlydryer_kind": kind,
            "type": "service",
            "sale_ok": True,
            "purchase_ok": False,
            "available_in_pos": True,
            "invoice_policy": "order",
        }
        if pos_category:
            vals["pos_categ_ids"] = [fields.Command.set(pos_category.ids)]
        return vals

    @api.model
    def _earlydryer_laundry_name(self, category, service_type):
        return f"{category.name} - {service_type.name}"

    @api.model
    def _earlydryer_laundry_code(self, category, service_type):
        return f"{category.code}-{service_type.code}"
