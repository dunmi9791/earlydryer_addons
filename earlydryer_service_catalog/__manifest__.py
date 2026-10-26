# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Earlydryer Service Catalogue",
    "summary": "Garments, services, surcharges, plant/channel price lists and "
    "turnaround promises for Earlydryer",
    "version": "19.0.1.0.0",
    "category": "Earlydryer",
    "author": "Secteur",
    "license": "LGPL-3",
    "depends": [
        "earlydryer_base",
        "product",
        "sale",
        "point_of_sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/earlydryer_catalog_rules.xml",
        "data/pos_category_data.xml",
        "data/earlydryer_garment_category_data.xml",
        "data/earlydryer_service_type_data.xml",
        "data/product_data.xml",
        "data/auditlog_rule_data.xml",
        "wizards/earlydryer_catalog_generate_wizard_views.xml",
        "wizards/earlydryer_pricelist_version_wizard_views.xml",
        "wizards/earlydryer_price_check_wizard_views.xml",
        "views/earlydryer_garment_category_views.xml",
        "views/earlydryer_service_type_views.xml",
        "views/earlydryer_surcharge_views.xml",
        "views/product_template_views.xml",
        "views/product_pricelist_views.xml",
        "views/earlydryer_branch_views.xml",
        "views/earlydryer_catalog_menus.xml",
    ],
    "demo": [
        "demo/earlydryer_catalog_demo.xml",
    ],
    "post_init_hook": "post_init_hook",
}
