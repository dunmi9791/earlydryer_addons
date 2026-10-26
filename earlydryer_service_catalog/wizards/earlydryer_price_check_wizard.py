# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.product_pricelist import EARLYDRYER_CHANNELS


class EarlydryerPriceCheckWizard(models.TransientModel):
    """Show the ``earlydryer.catalog.price_item`` breakdown (workshop tool)."""

    _name = "earlydryer.price.check.wizard"
    _description = "Earlydryer Price Check"

    branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        default=lambda self: self.env.user.earlydryer_branch_id,
    )
    channel = fields.Selection(EARLYDRYER_CHANNELS, required=True, default="walk_in")
    partner_id = fields.Many2one("res.partner", string="Customer")
    category_id = fields.Many2one(
        "earlydryer.garment.category", string="Garment", required=True
    )
    service_type_id = fields.Many2one(
        "earlydryer.service.type", string="Service", required=True
    )
    surcharge_ids = fields.Many2many("earlydryer.surcharge", string="Surcharges")
    express = fields.Boolean()
    quantity = fields.Integer(default=1)
    date = fields.Datetime(default=fields.Datetime.now, string="Price Date")

    product_id = fields.Many2one("product.product", compute="_compute_result")
    pricelist_id = fields.Many2one("product.pricelist", compute="_compute_result")
    currency_id = fields.Many2one("res.currency", compute="_compute_result")
    unit_price = fields.Monetary(compute="_compute_result")
    total = fields.Monetary(compute="_compute_result")
    promised_datetime = fields.Datetime(compute="_compute_result", string="Ready By")
    breakdown = fields.Html(compute="_compute_result", sanitize=False)
    error = fields.Char(compute="_compute_result")

    @api.depends(
        "branch_id",
        "channel",
        "partner_id",
        "category_id",
        "service_type_id",
        "surcharge_ids",
        "express",
        "quantity",
        "date",
    )
    def _compute_result(self):
        Catalog = self.env["earlydryer.catalog"]
        for wizard in self:
            wizard.update(
                {
                    "product_id": False,
                    "pricelist_id": False,
                    "currency_id": self.env.company.currency_id,
                    "unit_price": 0.0,
                    "total": 0.0,
                    "promised_datetime": False,
                    "breakdown": False,
                    "error": False,
                }
            )
            if not (wizard.category_id and wizard.service_type_id and wizard.channel):
                continue
            try:
                product = Catalog.get_laundry_product(
                    wizard.category_id, wizard.service_type_id
                )
                result = Catalog.price_item(
                    product,
                    wizard.partner_id,
                    wizard.branch_id,
                    wizard.channel,
                    surcharges=wizard.surcharge_ids,
                    express=wizard.express,
                    date=wizard.date,
                    quantity=max(wizard.quantity, 1),
                )
            except UserError as error:
                wizard.error = str(error)
                continue
            currency = self.env["res.currency"].browse(result["currency_id"])
            wizard.update(
                {
                    "product_id": product,
                    "pricelist_id": result["pricelist_id"],
                    "currency_id": currency,
                    "unit_price": result["unit_price"],
                    "total": result["total"],
                    "promised_datetime": Catalog.promised_datetime(
                        product, wizard.branch_id, express=wizard.express
                    ),
                    "breakdown": wizard._render_breakdown(product, result, currency),
                }
            )

    def _render_breakdown(self, product, result, currency):
        Product = self.env["product.product"]
        rows = [(product.display_name, result["unit_price"])]
        surcharges = {s.id: s for s in self.surcharge_ids}
        for line in result["surcharge_lines"]:
            rows.append(
                (surcharges[line["surcharge_id"]].display_name, line["unit_price"])
            )
        if result["express_line"]:
            rows.append(
                (
                    Product.browse(result["express_line"]["product_id"]).display_name,
                    result["express_line"]["unit_price"],
                )
            )
        body = Markup("").join(
            Markup('<tr><td>%s</td><td class="text-end">%s</td></tr>')
            % (escape(label), currency.format(amount))
            for label, amount in rows
        )
        return Markup('<table class="table table-sm"><tbody>%s</tbody></table>') % body
