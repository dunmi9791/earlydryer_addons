# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        res = super()._post_load_data(template_code, company, template_data)
        # a chart loaded after this module: create the wallet accounts now
        company._earlydryer_wallet_setup()
        return res
