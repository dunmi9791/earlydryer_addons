# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        # a till opening offline-capable must hold enough tag numbers
        try:
            with self.env.cr.savepoint():
                self.env["earlydryer.tag.range"].sudo()._earlydryer_top_up(
                    sessions.config_id
                )
        except Exception:  # pylint: disable=broad-except  # never block the till
            _logger.exception("Tag range top-up failed on POS session open.")
        return sessions
