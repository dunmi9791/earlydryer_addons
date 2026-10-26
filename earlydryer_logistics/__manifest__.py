# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Earlydryer Logistics",
    "summary": "Pickups and deliveries: zones, fees, slots, trips, rider view, "
    "cash on delivery",
    "version": "19.0.1.0.0",
    "category": "Earlydryer",
    "author": "Secteur",
    "license": "LGPL-3",
    "application": False,
    "installable": True,
    # earlydryer_reporting (the KPI registry of the build prompt) does not
    # exist on the addons path: earlydryer_notifications is the top of the
    # installed Earlydryer chain (base > ... > pos > wallet > accounting_ng >
    # notifications). The logistics KPIs live here (see README).
    "depends": [
        "earlydryer_notifications",
        "base_location",
        # vehicles, odometer logs (Community)
        "fleet",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/earlydryer_logistics_rules.xml",
        "data/product_data.xml",
        "data/earlydryer_area_data.xml",
        "data/earlydryer_fail_reason_data.xml",
        "data/notify_event_data.xml",
        "data/notify_alert_rule_data.xml",
        "data/auditlog_rule_data.xml",
        "report/route_sheet_report.xml",
        "wizards/earlydryer_logistics_schedule_wizard_views.xml",
        "wizards/earlydryer_logistics_outcome_wizard_views.xml",
        "wizards/earlydryer_logistics_plan_wizard_views.xml",
        "wizards/earlydryer_logistics_close_wizard_views.xml",
        "views/earlydryer_area_views.xml",
        "views/earlydryer_delivery_zone_views.xml",
        "views/earlydryer_slot_template_views.xml",
        "views/earlydryer_fail_reason_views.xml",
        "views/earlydryer_logistics_stop_views.xml",
        "views/earlydryer_logistics_trip_views.xml",
        "views/earlydryer_logistics_dashboard_views.xml",
        "views/earlydryer_branch_views.xml",
        "views/res_partner_views.xml",
        "views/hr_employee_views.xml",
        "views/laundry_job_views.xml",
        "views/res_config_settings_views.xml",
        "views/earlydryer_logistics_menus.xml",
    ],
    "demo": [
        "demo/earlydryer_logistics_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "earlydryer_logistics/static/src/rider/**/*",
        ],
        "point_of_sale._assets_pos": [
            "earlydryer_logistics/static/src/pos/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
}
