# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64

from odoo import models
from odoo.tools import file_open


class ThemeUtils(models.AbstractModel):
    _inherit = "theme.utils"

    @property
    def _footer_templates(self):
        return ["theme_earlydryer.template_footer_earlydryer"] + super()._footer_templates

    def _theme_earlydryer_post_copy(self, mod):
        self.enable_view("website.template_header_default")
        self.enable_view("theme_earlydryer.template_footer_earlydryer")
        website = self.env["website"].browse(self.env.context.get("website_id"))
        if website:
            website.write(
                {
                    "logo": self._earlydryer_image("static/src/img/logo.png"),
                    "favicon": self._earlydryer_image("static/description/icon.png"),
                }
            )

    def _earlydryer_image(self, path):
        with file_open(f"theme_earlydryer/{path}", "rb") as image:
            return base64.b64encode(image.read())
