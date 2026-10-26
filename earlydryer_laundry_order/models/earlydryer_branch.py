# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class EarlydryerBranch(models.Model):
    _inherit = "earlydryer.branch"

    laundry_job_sequence_id = fields.Many2one(
        "ir.sequence",
        string="Job Sequence",
        readonly=True,
        copy=False,
        help="Numbering of the laundry jobs of this plant: <CODE>/<YY>/<00001>, "
        "restarting every year.",
    )

    def _laundry_job_sequence_prefix(self):
        self.ensure_one()
        # range_y: year of the yearly sub-sequence (use_date_range)
        return f"{self.code}/%(range_y)s/"

    def _laundry_job_ensure_sequence(self):
        """Create the job sequence of the branches that have none."""
        Sequence = self.env["ir.sequence"].sudo()
        for branch in self.filtered(lambda b: not b.laundry_job_sequence_id):
            branch.sudo().laundry_job_sequence_id = Sequence.create(
                {
                    "name": self.env._(
                        "Laundry Jobs %(branch)s", branch=branch.display_name
                    ),
                    "code": f"laundry.job.{branch.id}",
                    "prefix": branch._laundry_job_sequence_prefix(),
                    "padding": 5,
                    "use_date_range": True,
                    "company_id": branch.company_id.id,
                }
            )
        return self.laundry_job_sequence_id

    @api.model_create_multi
    def create(self, vals_list):
        branches = super().create(vals_list)
        branches._laundry_job_ensure_sequence()
        return branches

    def write(self, vals):
        res = super().write(vals)
        if "code" in vals:
            for branch in self.filtered("laundry_job_sequence_id"):
                branch.laundry_job_sequence_id.sudo().prefix = (
                    branch._laundry_job_sequence_prefix()
                )
        return res
