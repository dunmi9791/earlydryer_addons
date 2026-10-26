# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models
from odoo.tools.misc import format_datetime

from .report_garment_tag import label_layout


class ReportBagLabel(models.AbstractModel):
    _name = "report.earlydryer_tagging.report_bag_label"
    _description = "Earlydryer Bag Label Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["laundry.job"].browse(docids)
        paperformat = self.env[
            "report.earlydryer_tagging.report_garment_tag"
        ]._earlydryer_paperformat(
            "earlydryer_tagging.report_bag_label", docs, "bag_label_paperformat_id"
        )
        labels = []
        for job in docs:
            labels.append(
                {
                    "job": job.name,
                    "customer": job._earlydryer_customer_short_name(),
                    "item_count": job.item_count,
                    "shelf": job.shelf_id.display_name or "",
                    "promised": format_datetime(
                        self.env, job.promised_on, dt_format="EEE dd/MM HH:mm"
                    )
                    if job.promised_on
                    else "",
                    "express": job.express,
                    "branch": job.earlydryer_branch_id.display_name,
                    "fulfilment": dict(
                        job._fields["fulfilment"]._description_selection(self.env)
                    ).get(job.fulfilment, ""),
                }
            )
        return {
            "doc_ids": docs.ids,
            "doc_model": "laundry.job",
            "docs": docs,
            "labels": labels,
            "layout": label_layout(paperformat),
            "paperformat": paperformat,
        }
