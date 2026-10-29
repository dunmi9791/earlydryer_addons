# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
# ruff: noqa: B018 -- Odoo manifests are dictionary literals.
{
    "name": "Earlydryer Website Pickup",
    "summary": "Book a pickup on the website; follow and cancel it in the portal",
    "version": "19.0.1.0.0",
    "category": "Earlydryer",
    "author": "Secteur",
    "license": "LGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "earlydryer_logistics",
        "website",
        "portal",
    ],
    "data": [
        "views/pickup_templates.xml",
        "views/portal_templates.xml",
    ],
}
