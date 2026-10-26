# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models, tools
from odoo.tools import SQL


class ReportItem(models.Model):
    _name = "earlydryer.report.item"
    _description = "Earlydryer Garment Analysis"
    _auto = False
    item_id = fields.Many2one("laundry.job.item", readonly=True)
    job_id = fields.Many2one("laundry.job", readonly=True)
    earlydryer_branch_id = fields.Many2one("earlydryer.branch", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    received_date = fields.Date(readonly=True)
    ready_date = fields.Date(readonly=True)
    garment_category_id = fields.Many2one("earlydryer.garment.category", readonly=True)
    service_type_id = fields.Many2one("earlydryer.service.type", readonly=True)
    service_line_id = fields.Many2one("account.analytic.account", readonly=True)
    express = fields.Boolean(readonly=True)
    price = fields.Float(readonly=True)
    rework_count = fields.Integer(readonly=True)
    missing = fields.Boolean(readonly=True)
    missing_on = fields.Datetime(readonly=True)
    estimated_weight_kg = fields.Float(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            SQL("""CREATE VIEW earlydryer_report_item AS SELECT i.id,i.id item_id,i.job_id,j.earlydryer_branch_id,j.company_id,
   (j.received_on AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date received_date,(j.ready_on AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date ready_date,i.garment_category_id,i.service_type_id,t.earlydryer_service_line_id service_line_id,j.express,
   i.price_unit price,i.rework_count,i.missing,i.earlydryer_missing_on missing_on,coalesce(c.average_weight_kg,0) estimated_weight_kg
   FROM laundry_job_item i JOIN laundry_job j ON j.id=i.job_id
   LEFT JOIN earlydryer_garment_category c ON c.id=i.garment_category_id
   LEFT JOIN earlydryer_service_type t ON t.id=i.service_type_id WHERE j.state!='cancelled'""")
        )
