# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
# ruff: noqa: B018 -- Odoo manifests are dictionary literals.
{
    "name": "Earlydryer Theme",
    "summary": "Earlydryer brand for the website: blue and sun-yellow, waves, "
    "pill buttons and a laundry homepage",
    "description": "Premium laundry & dry cleaning in Abuja.",
    "version": "19.0.1.0.0",
    "category": "Theme/Services",
    "sequence": 10,
    "author": "Secteur",
    "license": "LGPL-3",
    "installable": True,
    "depends": [
        "website",
    ],
    "data": [
        "data/ir_asset.xml",
        "data/images.xml",
        "data/menu.xml",
        "views/layout.xml",
        "views/homepage.xml",
    ],
    "images": [
        "static/description/icon.png",
    ],
}
