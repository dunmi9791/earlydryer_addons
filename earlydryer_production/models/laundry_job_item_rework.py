# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

from odoo.addons.earlydryer_laundry_order.models.laundry_job import STATES


class LaundryJobItemRework(models.Model):
    """One row per garment failed at QC: why, and where it went back to.

    Read later by earlydryer_claims (damage) and the reporting module.
    ``laundry.job.item.rework_count`` is kept by earlydryer_laundry_order.
    """

    _name = "laundry.job.item.rework"
    _description = "Laundry Job Item Rework"
    _order = "date desc, id desc"
    _rec_name = "item_id"

    item_id = fields.Many2one(
        "laundry.job.item", required=True, index=True, ondelete="cascade", readonly=True
    )
    job_id = fields.Many2one(
        related="item_id.job_id", store=True, index=True, string="Job"
    )
    earlydryer_branch_id = fields.Many2one(
        related="item_id.earlydryer_branch_id", store=True, index=True, string="Branch"
    )
    company_id = fields.Many2one(related="item_id.company_id", store=True)
    reason_id = fields.Many2one("earlydryer.rework.reason", index=True, readonly=True)
    is_damage = fields.Boolean(related="reason_id.is_damage", store=True)
    from_state = fields.Selection(STATES, string="From", readonly=True)
    to_state = fields.Selection(STATES, string="Sent Back To", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Checked By", readonly=True)
    user_id = fields.Many2one(
        "res.users",
        string="Recorded By",
        default=lambda self: self.env.user,
        readonly=True,
    )
    date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    note = fields.Text(readonly=True)
    photo_id = fields.Many2one("ir.attachment", readonly=True)
    photo = fields.Binary(related="photo_id.datas", string="Photo Image")
