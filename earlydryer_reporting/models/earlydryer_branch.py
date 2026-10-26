# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class EarlydryerBranch(models.Model):
    _inherit = "earlydryer.branch"

    def _earlydryer_eod_figures(self, date):
        self.ensure_one()
        return self.env["earlydryer.kpi"]._eod_figures(self, date)
