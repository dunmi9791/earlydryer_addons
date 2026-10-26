# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

# context key carrying the entry point of a stage move (see action_move_to)
SOURCE_CTX = "earlydryer_move_source"
SOURCES = [
    ("board", "Stage Board"),
    ("tablet", "Production Tablet"),
    ("scan", "Scan Screen"),
    ("batch", "Wash/Dry Batch"),
    ("qc", "QC"),
    ("form", "Job Form"),
    ("system", "System"),
]


class LaundryJobStageLog(models.Model):
    _inherit = "laundry.job.stage.log"

    item_count = fields.Integer(
        string="Garments",
        compute="_compute_item_count",
        store=True,
        aggregator="sum",
        help="Garments the move covered (the whole job when none were listed).",
    )
    source = fields.Selection(
        SOURCES,
        readonly=True,
        index=True,
        help="Where the move was recorded.",
    )
    move_count = fields.Integer(
        string="Moves", compute="_compute_move_count", store=True, aggregator="sum"
    )

    @api.depends("item_ids")
    def _compute_item_count(self):
        # the job's count at the time of the move: not recomputed when the
        # job's items change later
        for log in self:
            log.item_count = len(log.item_ids) or log.job_id.item_count

    @api.depends("job_id")
    def _compute_move_count(self):
        # constant 1: a summable measure for the pivot (``__count`` cannot be
        # combined with the item count in one graph)
        self.move_count = 1

    @api.model_create_multi
    def create(self, vals_list):
        source = self.env.context.get(SOURCE_CTX)
        if not source:
            source = "system" if self.env.su else "form"
        for vals in vals_list:
            vals.setdefault("source", source)
        return super().create(vals_list)
