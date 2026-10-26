# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Earlydryer Tagging",
    "summary": "Garment tags with barcodes: numbering per plant, labels, "
    "scanning to find, move and pack orders",
    "version": "19.0.1.0.0",
    "category": "Earlydryer",
    "author": "Secteur",
    "license": "LGPL-3",
    "depends": [
        "earlydryer_laundry_order",
        "barcodes",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/earlydryer_tagging_rules.xml",
        "report/report_paperformat_data.xml",
        "report/garment_tag_report.xml",
        "report/bag_label_report.xml",
        "data/ir_cron_data.xml",
        "data/ir_actions_server_data.xml",
        "wizards/earlydryer_tag_assign_wizard_views.xml",
        "wizards/earlydryer_tag_replace_wizard_views.xml",
        "views/earlydryer_branch_views.xml",
        "views/laundry_job_views.xml",
        "views/laundry_job_item_views.xml",
        "views/earlydryer_tag_range_views.xml",
        "views/earlydryer_scan_log_views.xml",
        "views/earlydryer_tagging_menus.xml",
    ],
    "demo": [
        "demo/earlydryer_tagging_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "earlydryer_tagging/static/src/scan_screen/*",
        ],
    },
    "post_init_hook": "post_init_hook",
}
