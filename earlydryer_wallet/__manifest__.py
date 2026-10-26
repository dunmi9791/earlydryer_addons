# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Earlydryer Wallet",
    "summary": "Prepaid customer balance held as a customer advance, spent on "
    "invoices, laundry jobs and at the till of either plant",
    "version": "19.0.1.0.0",
    "category": "Earlydryer",
    "author": "Secteur",
    "license": "LGPL-3",
    "depends": [
        "earlydryer_pos",
        "account",
    ],
    # openpyxl reads XLSX migration files; it ships with Odoo 19 (base_import)
    "external_dependencies": {"python": ["openpyxl"]},
    "data": [
        "security/ir.model.access.csv",
        "security/earlydryer_wallet_rules.xml",
        "data/ir_sequence_data.xml",
        "data/ir_config_parameter_data.xml",
        "data/earlydryer_approval_rule_data.xml",
        "data/product_data.xml",
        "data/auditlog_rule_data.xml",
        "report/wallet_statement_report.xml",
        "wizards/earlydryer_wallet_topup_wizard_views.xml",
        "wizards/earlydryer_wallet_refund_wizard_views.xml",
        "wizards/earlydryer_wallet_credit_wizard_views.xml",
        "wizards/earlydryer_wallet_spend_wizard_views.xml",
        "wizards/earlydryer_wallet_reverse_wizard_views.xml",
        "wizards/earlydryer_wallet_statement_wizard_views.xml",
        "wizards/earlydryer_wallet_import_wizard_views.xml",
        "wizards/earlydryer_wallet_control_views.xml",
        "views/earlydryer_wallet_transaction_views.xml",
        "views/earlydryer_wallet_views.xml",
        "views/res_partner_views.xml",
        "views/account_move_views.xml",
        "views/laundry_job_views.xml",
        "views/pos_config_views.xml",
        "views/pos_payment_method_views.xml",
        "views/pos_order_views.xml",
        "views/res_config_settings_views.xml",
        "views/earlydryer_wallet_menus.xml",
    ],
    "demo": [
        "demo/earlydryer_wallet_demo.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "earlydryer_wallet/static/src/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
}
