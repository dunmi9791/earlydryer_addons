# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
# ruff: noqa: B018 -- Odoo manifests are dictionary literals.

{
    "name": "Earlydryer Reporting",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "Secteur",
    "category": "Earlydryer",
    "depends": [
        "earlydryer_notifications",
        "mis_builder",
        "report_xlsx",
        "date_range",
        "web_responsive",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/report_views.xml",
        "views/subscription_views.xml",
        "report/reports.xml",
        "data/events.xml",
        "data/queue_cron.xml",
    ],
    "demo": ["demo/demo.xml"],
    "post_init_hook": "post_init_hook",
    "assets": {
        "web.assets_backend": ["earlydryer_reporting/static/src/**/*"],
        "web.assets_tests": ["earlydryer_reporting/static/tests/**/*"],
    },
}
