# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
# ruff: noqa: B018 -- Odoo manifests are dictionary literals.
{
    "name": "Earlydryer API",
    "summary": "REST API for the Earlydryer website and mobile app: online "
    "pickup booking",
    "version": "19.0.1.0.0",
    "category": "Earlydryer",
    "author": "Secteur",
    "license": "LGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "earlydryer_logistics",
        # OCA rest-framework
        "fastapi",
    ],
    "external_dependencies": {"python": ["fastapi", "pydantic"]},
    "data": [
        "data/earlydryer_api_data.xml",
        "views/fastapi_endpoint_views.xml",
    ],
}
