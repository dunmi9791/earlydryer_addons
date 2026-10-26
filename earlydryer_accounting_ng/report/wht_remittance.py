# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models


class ReportWhtRemittance(models.AbstractModel):
    _name = "report.earlydryer_accounting_ng.report_wht_remittance"
    _description = "Earlydryer WHT Remittance Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env["earlydryer.wht.report.wizard"].browse(docids)
        wizards._earlydryer_check_right()
        return {
            "doc_ids": docids,
            "doc_model": "earlydryer.wht.report.wizard",
            "docs": wizards,
            "rows": {wizard.id: wizard._earlydryer_rows() for wizard in wizards},
        }
