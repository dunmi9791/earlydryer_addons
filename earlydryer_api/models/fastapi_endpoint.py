# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import secrets

from fastapi import APIRouter

from odoo import fields, models

from ..routers import pickup_router


class FastapiEndpoint(models.Model):
    _inherit = "fastapi.endpoint"

    app = fields.Selection(
        selection_add=[("earlydryer", "Earlydryer API")],
        ondelete={"earlydryer": "cascade"},
    )
    earlydryer_api_key = fields.Char(
        string="API Key",
        copy=False,
        groups="base.group_system",
        default=lambda self: secrets.token_urlsafe(32),
        help="Sent by the website or app in the X-Api-Key header. Empty: "
        "every request is refused.",
    )

    def _get_fastapi_routers(self) -> list[APIRouter]:
        if self.app == "earlydryer":
            return [pickup_router]
        return super()._get_fastapi_routers()

    def action_earlydryer_new_api_key(self):
        """Replace the key (the old one stops working at once)."""
        for endpoint in self:
            endpoint.earlydryer_api_key = secrets.token_urlsafe(32)
        return True
