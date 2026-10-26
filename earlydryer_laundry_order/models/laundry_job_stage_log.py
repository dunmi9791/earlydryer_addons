# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import AccessError

from .laundry_job import STATES

ADMIN_GROUP = "earlydryer_base.group_admin"


class LaundryJobStageLog(models.Model):
    """One row per stage move of a laundry job; never edited afterwards.

    ``employee_id`` is who did the work (may have no Odoo login),
    ``user_id`` who recorded it. Feeds turnaround and productivity reports.
    """

    _name = "laundry.job.stage.log"
    _description = "Laundry Job Stage Log"
    _order = "date desc, id desc"
    _rec_name = "job_id"

    job_id = fields.Many2one(
        "laundry.job", required=True, index=True, ondelete="cascade", readonly=True
    )
    item_ids = fields.Many2many(
        "laundry.job.item",
        "laundry_job_stage_log_item_rel",
        "log_id",
        "item_id",
        string="Items",
        readonly=True,
        help="Items this move covered; empty means the whole job.",
    )
    from_state = fields.Selection(STATES, string="From", readonly=True)
    to_state = fields.Selection(
        STATES, string="To", required=True, index=True, readonly=True
    )
    date = fields.Datetime(
        required=True, index=True, default=fields.Datetime.now, readonly=True
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Done By",
        index="btree_not_null",
        readonly=True,
        help="Who did the work.",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Recorded By",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    earlydryer_branch_id = fields.Many2one(
        related="job_id.earlydryer_branch_id", store=True, index=True
    )
    company_id = fields.Many2one(related="job_id.company_id", store=True)
    duration_hours = fields.Float(
        string="Duration (h)",
        compute="_compute_duration_hours",
        store=True,
        aggregator="avg",
        digits=(16, 2),
        help="Hours since the previous move of the job (since drop-off for the "
        "first one).",
    )
    note = fields.Text(readonly=True)

    @api.depends("job_id", "date")
    def _compute_duration_hours(self):
        for log in self:
            if not log.job_id or not log.date:
                log.duration_hours = 0.0
                continue
            previous = self.sudo().search(
                [
                    ("job_id", "=", log.job_id.id),
                    ("id", "!=", log.id),
                    "|",
                    ("date", "<", log.date),
                    "&",
                    ("date", "=", log.date),
                    ("id", "<", log.id),
                ],
                order="date desc, id desc",
                limit=1,
            )
            start = previous.date if previous else log.job_id.received_on
            hours = (log.date - start).total_seconds() / 3600.0 if start else 0.0
            log.duration_hours = max(hours, 0.0)

    def _earlydryer_check_admin(self):
        if not self.env.su and not self.env.user.has_group(ADMIN_GROUP):
            raise AccessError(
                self.env._("The stage history of a laundry job cannot be changed.")
            )

    def write(self, vals):
        self._earlydryer_check_admin()
        return super().write(vals)

    def unlink(self):
        self._earlydryer_check_admin()
        return super().unlink()
