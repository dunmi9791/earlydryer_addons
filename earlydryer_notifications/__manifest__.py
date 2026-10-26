# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Earlydryer Notifications",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "Secteur",
    "category": "Earlydryer",
    "depends": ["earlydryer_accounting_ng", "queue_job", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/events.xml",
        "data/queue.xml",
        "data/cron.xml",
        "data/alerts.xml",
        "views/notify_views.xml",
        "views/inherited_views.xml",
        "data/audit.xml",
    ],
    "demo": ["demo/notifications.xml"],
    "assets": {"point_of_sale._assets_pos": ["earlydryer_notifications/static/src/*"]},
    "post_init_hook": "post_init_hook",
}
