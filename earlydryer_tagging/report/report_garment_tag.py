# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models

from ..models.ir_actions_report import PAPERFORMAT_CTX

# labels at most this high (mm) use the one-line strip layout (heat-seal)
STRIP_MAX_HEIGHT = 20


def label_layout(paperformat):
    """``sheet`` (A4/Letter sheet of labels), ``strip`` or ``label``."""
    if not paperformat or paperformat.format != "custom":
        return "sheet"
    if paperformat.page_height and paperformat.page_height <= STRIP_MAX_HEIGHT:
        return "strip"
    return "label"


class ReportGarmentTag(models.AbstractModel):
    _name = "report.earlydryer_tagging.report_garment_tag"
    _description = "Earlydryer Garment Tag Report"

    @api.model
    def _earlydryer_paperformat(self, report_name, docs, fname):
        paperformat_id = self.env.context.get(PAPERFORMAT_CTX)
        if paperformat_id:
            return self.env["report.paperformat"].browse(paperformat_id)
        report = self.env["ir.actions.report"]._get_report_from_name(report_name)
        branch = docs[:1].sudo().earlydryer_branch_id
        return branch[fname] or report.get_paperformat()

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["laundry.job.item"].browse(docids).filtered("tag_code")
        paperformat = self._earlydryer_paperformat(
            "earlydryer_tagging.report_garment_tag", docs, "tag_label_paperformat_id"
        )
        return {
            "doc_ids": docs.ids,
            "doc_model": "laundry.job.item",
            "docs": docs,
            "labels": [item._earlydryer_label_values() for item in docs],
            "layout": label_layout(paperformat),
            "paperformat": paperformat,
        }
