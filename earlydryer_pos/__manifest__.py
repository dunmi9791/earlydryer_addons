# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Earlydryer POS",
    "summary": "Laundry intake, tags, receipts and collection at the plant "
    "counter, online and offline",
    "version": "19.0.1.0.0",
    "category": "Earlydryer",
    "author": "Secteur",
    "license": "LGPL-3",
    "depends": [
        "earlydryer_tagging",
        "point_of_sale",
        "pos_hr",
        "queue_job",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/earlydryer_pos_rules.xml",
        "data/product_data.xml",
        "data/queue_job_data.xml",
        "data/auditlog_rule_data.xml",
        "views/res_config_settings_views.xml",
        "views/pos_config_views.xml",
        "views/pos_order_views.xml",
        "views/laundry_job_views.xml",
        "views/earlydryer_pos_collection_views.xml",
        "views/earlydryer_pos_pin_approval_views.xml",
        "views/earlydryer_pos_menus.xml",
    ],
    "demo": [
        "demo/earlydryer_pos_demo.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "earlydryer_pos/static/lib/jsbarcode/JsBarcode.code128.min.js",
            "earlydryer_pos/static/src/**/*",
        ],
        "web.assets_tests": [
            "earlydryer_pos/static/tests/tours/**/*",
        ],
        "web.assets_unit_tests": [
            "earlydryer_pos/static/tests/unit/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
}
