# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models

# context key: paperformat of the label being printed
PAPERFORMAT_CTX = "earlydryer_label_paperformat_id"
# report name -> (model, branch field holding the label size)
LABEL_REPORTS = {
    "earlydryer_tagging.report_garment_tag": (
        "laundry.job.item",
        "tag_label_paperformat_id",
    ),
    "earlydryer_tagging.report_bag_label": ("laundry.job", "bag_label_paperformat_id"),
}


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def get_paperformat(self):
        """Labels print on the size set on their plant (or forced by context)."""
        if self.report_name in LABEL_REPORTS and self.env.context.get(PAPERFORMAT_CTX):
            return self.env["report.paperformat"].browse(
                self.env.context[PAPERFORMAT_CTX]
            )
        return super().get_paperformat()

    def _earlydryer_label_paperformat(self, report_name, res_ids):
        """Label size of the first plant among the printed records."""
        model, fname = LABEL_REPORTS[report_name]
        records = self.env[model].sudo().browse(res_ids or [])
        branch = records[:1].earlydryer_branch_id
        return branch[fname] if branch else self.env["report.paperformat"]

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        report = self._get_report(report_ref)
        reports = self
        if report.report_name in LABEL_REPORTS and not self.env.context.get(
            PAPERFORMAT_CTX
        ):
            paperformat = self._earlydryer_label_paperformat(
                report.report_name, res_ids
            )
            if paperformat:
                reports = self.with_context(**{PAPERFORMAT_CTX: paperformat.id})
        return super(IrActionsReport, reports)._render_qweb_pdf_prepare_streams(
            report_ref, data, res_ids
        )
