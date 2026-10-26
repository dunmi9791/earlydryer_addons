# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.fields import Command

from odoo.addons.earlydryer_base.tests.common import EarlydryerCommon


class CatalogCommon(EarlydryerCommon):
    """Test catalogue independent of the shipped data and demo data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Catalog = cls.env["earlydryer.catalog"]
        cls.Category = cls.env["earlydryer.garment.category"]
        cls.Service = cls.env["earlydryer.service.type"]
        cls.Surcharge = cls.env["earlydryer.surcharge"]
        cls.Pricelist = cls.env["product.pricelist"]
        cls.Item = cls.env["product.pricelist.item"]
        cls.currency = cls.env.company.currency_id

        cls.cat_shirt = cls.Category.create(
            {"name": "T Shirt", "code": "tshirt", "garment_group": "tops"}
        )
        cls.cat_rug = cls.Category.create(
            {"name": "T Rug", "code": "TRUG", "garment_group": "household"}
        )
        cls.svc_wi = cls.Service.create(
            {
                "name": "T Wash & Iron",
                "code": "TWI",
                "standard_turnaround_hours": 16,
                "express_available": True,
                "express_turnaround_hours": 4,
                "express_surcharge_kind": "percent",
                "express_surcharge_value": 50,
            }
        )
        cls.svc_dc = cls.Service.create(
            {
                "name": "T Dry Cleaning",
                "code": "TDC",
                "standard_turnaround_hours": 24,
                "express_available": True,
                "express_turnaround_hours": 8,
                "express_surcharge_kind": "fixed",
                "express_surcharge_value": 700,
            }
        )
        cls.svc_rug = cls.Service.create(
            {
                "name": "T Rug Cleaning",
                "code": "TRUGC",
                "standard_turnaround_hours": 40,
                "allowed_category_ids": [Command.set(cls.cat_rug.ids)],
            }
        )
        cls.Catalog._generate_laundry_products(
            cls.cat_shirt | cls.cat_rug, cls.svc_wi | cls.svc_dc | cls.svc_rug
        )
        cls.shirt_wi = cls.Catalog.get_laundry_product(cls.cat_shirt, cls.svc_wi)
        cls.shirt_dc = cls.Catalog.get_laundry_product(cls.cat_shirt, cls.svc_dc)
        cls.rug_rug = cls.Catalog.get_laundry_product(cls.cat_rug, cls.svc_rug)
        (cls.shirt_wi | cls.shirt_dc | cls.rug_rug).list_price = 100

        cls.sur_beads = cls.Surcharge.create(
            {
                "name": "T Beads",
                "code": "TBEAD",
                "kind": "embellishment",
                "compute_mode": "fixed",
                "amount": 300,
            }
        )
        cls.sur_silk = cls.Surcharge.create(
            {
                "name": "T Silk",
                "code": "TSILK",
                "kind": "fabric",
                "compute_mode": "percent",
                "percent": 25,
                "category_ids": [Command.set(cls.cat_shirt.ids)],
            }
        )

        cls.pl_walk_in_b1 = cls.Pricelist.create(
            {
                "name": "T Walk-in B1",
                "earlydryer_channel": "walk_in",
                "earlydryer_branch_id": cls.branch_1.id,
                "item_ids": [
                    Command.create(cls._fixed_item(cls.shirt_wi, 1000)),
                    Command.create(cls._fixed_item(cls.shirt_dc, 2000)),
                    Command.create(cls._fixed_item(cls.sur_beads.product_id, 500)),
                ],
            }
        )

    @classmethod
    def _fixed_item(cls, product, price, **kwargs):
        return {
            "applied_on": "1_product",
            "product_tmpl_id": product.product_tmpl_id.id,
            "compute_price": "fixed",
            "fixed_price": price,
            **kwargs,
        }
