# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models, tools
from odoo.tools import SQL


class ReportStage(models.Model):
    _name = "earlydryer.report.stage"
    _description = "Earlydryer Staff Productivity"
    _auto = False
    _order = "date desc,id desc"
    _depends = {  # noqa: RUF012 -- Odoo model metadata.
        "laundry.job.stage.log": [
            "job_id",
            "earlydryer_branch_id",
            "company_id",
            "date",
            "employee_id",
            "user_id",
            "from_state",
            "to_state",
            "duration_hours",
            "earlydryer_release_unpaid",
            "item_ids",
        ],
        "laundry.job": ["state", "item_count"],
        "hr.employee": ["earlydryer_branch_id"],
    }
    job_id = fields.Many2one("laundry.job", readonly=True)
    earlydryer_branch_id = fields.Many2one("earlydryer.branch", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    date = fields.Datetime(readonly=True)
    local_date = fields.Date(readonly=True)
    employee_id = fields.Many2one("hr.employee", readonly=True)
    user_id = fields.Many2one("res.users", readonly=True)
    from_state = fields.Char(readonly=True)
    to_state = fields.Char(readonly=True)
    items_moved = fields.Integer(readonly=True)
    moves = fields.Integer(readonly=True)
    earlydryer_release_unpaid = fields.Boolean(
        readonly=True, groups="earlydryer_base.group_branch_manager"
    )
    hours_in_stage = fields.Float(readonly=True, aggregator="avg")
    source = fields.Char(readonly=True)
    no_employee = fields.Boolean(readonly=True)
    outside_plant = fields.Boolean(readonly=True)
    fast_move = fields.Boolean(compute="_compute_fast_move", search="_search_fast_move")

    def _compute_fast_move(self):
        minimum = float(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("earlydryer_reporting.min_minutes_per_item", 0.5)
        )
        for row in self:
            row.fast_move = bool(
                row.items_moved
                and row.hours_in_stage * 60 / row.items_moved < minimum
                and row.from_state
                in ("sorted", "washed", "dried", "ironed", "qc", "packed")
            )

    def _search_fast_move(self, operator, value):
        from odoo.fields import Domain

        if operator not in ("in", "not in"):
            return NotImplemented
        minimum = float(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("earlydryer_reporting.min_minutes_per_item", 0.5)
        )
        self.env.cr.execute(
            SQL(
                "SELECT id FROM earlydryer_report_stage WHERE items_moved>0 AND hours_in_stage*60/items_moved<%s AND from_state IN ('sorted','washed','dried','ironed','qc','packed')",
                minimum,
            )
        )
        domain = Domain("id", "in", [row[0] for row in self.env.cr.fetchall()])
        return domain if (True in value) == (operator == "in") else ~domain

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Read optional Production columns at query time, including when that
        # addon is installed later in the same registry upgrade.
        count = SQL(
            "coalesce((to_jsonb(s)->>'item_count')::integer,nullif(covered.item_count,0),j.item_count)"
        )
        source = SQL("coalesce(to_jsonb(s)->>'source','form')")
        self.env.cr.execute(
            SQL(
                """CREATE VIEW earlydryer_report_stage AS SELECT s.id,s.job_id,s.earlydryer_branch_id,s.company_id,s.date,
   (s.date AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date local_date,s.employee_id,s.user_id,s.from_state,s.to_state,
   %s::integer items_moved,1::integer moves,s.duration_hours hours_in_stage,%s source,
   (s.employee_id IS NULL AND s.from_state IN ('sorted','washed','dried','ironed','qc','packed')) no_employee,
   s.earlydryer_release_unpaid,
   (e.earlydryer_branch_id IS NOT NULL AND e.earlydryer_branch_id!=s.earlydryer_branch_id) outside_plant
   FROM laundry_job_stage_log s JOIN laundry_job j ON j.id=s.job_id LEFT JOIN hr_employee e ON e.id=s.employee_id LEFT JOIN (SELECT log_id,count(*) item_count FROM laundry_job_stage_log_item_rel GROUP BY log_id) covered ON covered.log_id=s.id WHERE j.state!='cancelled'""",
                count,
                source,
            )
        )
        self.env.cr.execute(
            SQL(
                "CREATE INDEX IF NOT EXISTS earlydryer_reporting_stage_branch_date ON laundry_job_stage_log(earlydryer_branch_id,date)"
            )
        )
