# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json

from odoo import api, models


class PackReport(models.AbstractModel):
    _name = "report.earlydryer_reporting.pack_document"
    _description = "Earlydryer Performance Pack PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["earlydryer.report.pack"].browse(docids)
        docs.check_access("read")
        return {
            "docs": docs,
            "reports": [(pack, json.loads(pack.data_json or "{}")) for pack in docs],
        }
