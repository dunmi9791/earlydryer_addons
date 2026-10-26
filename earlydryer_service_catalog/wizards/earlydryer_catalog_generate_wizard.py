# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class EarlydryerCatalogGenerateWizard(models.TransientModel):
    _name = "earlydryer.catalog.generate.wizard"
    _description = "Generate Earlydryer Laundry Products"

    category_ids = fields.Many2many(
        "earlydryer.garment.category",
        "earlydryer_catalog_generate_category_rel",
        "wizard_id",
        "category_id",
        string="Garment Categories",
        default=lambda self: self.env["earlydryer.garment.category"].search([]),
    )
    service_type_ids = fields.Many2many(
        "earlydryer.service.type",
        "earlydryer_catalog_generate_service_type_rel",
        "wizard_id",
        "service_type_id",
        string="Service Types",
        default=lambda self: self.env["earlydryer.service.type"].search([]),
    )
    list_price = fields.Float(
        string="Default Sales Price",
        digits="Product Price",
        help="Sales price of the new products; real prices go on the price lists.",
    )
    tax_ids = fields.Many2many(
        "account.tax",
        "earlydryer_catalog_generate_tax_rel",
        "wizard_id",
        "tax_id",
        string="Sales Taxes",
        domain=[("type_tax_use", "=", "sale")],
        help="None by default: VAT (7.5%) only applies if Earlydryer is "
        "VAT-registered, which is not confirmed yet.",
    )
    income_account_id = fields.Many2one(
        "account.account",
        domain=[("account_type", "in", ["income", "income_other"])],
        help="Leave empty to use the income account of the product category.",
    )
    combination_count = fields.Integer(
        string="Combinations", compute="_compute_combination_count"
    )

    @api.depends("category_ids", "service_type_ids")
    def _compute_combination_count(self):
        for wizard in self:
            wizard.combination_count = sum(
                len(wizard.category_ids.filtered(service._allows_category))
                for service in wizard.service_type_ids
            )

    def action_generate(self):
        self.ensure_one()
        created, skipped = self.env["earlydryer.catalog"]._generate_laundry_products(
            self.category_ids,
            self.service_type_ids,
            list_price=self.list_price,
            taxes=self.tax_ids,
            income_account=self.income_account_id,
        )
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_service_catalog.product_template_action_laundry"
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success" if created else "info",
                "title": self.env._("Catalogue generated"),
                "message": self.env._(
                    "%(created)s products created, %(skipped)s existing skipped.",
                    created=len(created),
                    skipped=skipped,
                ),
                "next": action,
            },
        }
