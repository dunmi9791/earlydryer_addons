# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Earlydryer Production",
    "summary": "Stage board, production tablet, sorting, wash/dry batches, QC "
    "with rework reasons and machine status for the plants",
    "version": "19.0.1.0.0",
    "category": "Earlydryer",
    "author": "Secteur",
    "license": "LGPL-3",
    "depends": [
        "earlydryer_tagging",
        "maintenance",
        "hr",
        "bus",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/earlydryer_production_rules.xml",
        "data/earlydryer_rework_reason_data.xml",
        "report/report_paperformat_data.xml",
        "report/employee_badge_report.xml",
        "wizards/earlydryer_sort_wizard_views.xml",
        "wizards/earlydryer_qc_wizard_views.xml",
        "wizards/earlydryer_breakdown_wizard_views.xml",
        "views/earlydryer_branch_views.xml",
        "views/earlydryer_service_type_views.xml",
        "views/earlydryer_rework_reason_views.xml",
        "views/earlydryer_wash_batch_views.xml",
        "views/earlydryer_tablet_identification_views.xml",
        "views/hr_employee_views.xml",
        "views/laundry_job_views.xml",
        "views/laundry_job_item_rework_views.xml",
        "views/laundry_job_stage_log_views.xml",
        "views/maintenance_equipment_views.xml",
        "views/earlydryer_production_menus.xml",
    ],
    "demo": [
        "demo/earlydryer_production_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "earlydryer_production/static/src/stage_board/*",
        ],
        "web.assets_tests": [
            "earlydryer_production/static/tests/tours/*",
        ],
    },
    "post_init_hook": "post_init_hook",
}
