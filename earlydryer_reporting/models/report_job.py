# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models, tools
from odoo.tools import SQL


class ReportJob(models.Model):
    _name = "earlydryer.report.job"
    _description = "Earlydryer Job Analysis"
    _auto = False
    _rec_name = "name"
    _order = "received_on desc,id desc"
    job_id = fields.Many2one("laundry.job", readonly=True)
    name = fields.Char(readonly=True)
    earlydryer_branch_id = fields.Many2one("earlydryer.branch", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    channel = fields.Char(readonly=True)
    express = fields.Boolean(readonly=True)
    fulfilment = fields.Char(readonly=True)
    state = fields.Char(readonly=True)
    received_on = fields.Datetime(readonly=True)
    received_date = fields.Date(readonly=True)
    ready_on = fields.Datetime(readonly=True)
    ready_date = fields.Date(readonly=True)
    closed_on = fields.Datetime(readonly=True)
    closed_date = fields.Date(readonly=True)
    item_count = fields.Integer(readonly=True)
    amount_total = fields.Float(readonly=True)
    discount_amount = fields.Float(readonly=True)
    amount_due = fields.Float(compute="_compute_due")
    turnaround_hours = fields.Float(readonly=True, aggregator="avg")
    on_time = fields.Boolean(readonly=True)
    is_overdue = fields.Boolean(readonly=True)
    released_unpaid = fields.Boolean(readonly=True)
    is_first_job = fields.Boolean(readonly=True)
    first_received_date = fields.Date(readonly=True)
    rework_items_count = fields.Integer(readonly=True)

    def _compute_due(self):
        # The source's live residual allocation includes settlements and wallet credits.
        # Delegate, rather than duplicate accounting allocation in a SQL approximation.
        jobs = self.mapped("job_id")
        jobs.invalidate_recordset(
            ["amount_total", "amount_paid", "amount_due", "is_unpaid"]
        )
        source = {job.id: job.amount_due for job in jobs}
        for row in self:
            row.amount_due = source.get(row.job_id.id, 0)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            SQL("""CREATE VIEW earlydryer_report_job AS
   WITH first_customer AS (SELECT company_id,partner_id,min(id) first_id,min(received_on) first_received_on FROM (SELECT id,company_id,partner_id,received_on,row_number() OVER(PARTITION BY company_id,partner_id ORDER BY received_on,id) position FROM laundry_job WHERE state!='cancelled') ranked WHERE position=1 GROUP BY company_id,partner_id),
   items AS (SELECT job_id,count(*) item_count,count(*) FILTER(WHERE rework_count>0) rework_items_count
     FROM laundry_job_item GROUP BY job_id),
   pos_settlements AS (SELECT l.order_id,sum(l.price_subtotal_incl) amount FROM pos_order_line l
     JOIN product_product p ON p.id=l.product_id JOIN product_template t ON t.id=p.product_tmpl_id
     WHERE t.earlydryer_kind='settlement' GROUP BY l.order_id),
   discounts AS (SELECT order_id,sum(price_unit*product_uom_qty*discount/100) amount FROM sale_order_line GROUP BY order_id),
   pos_discounts AS (SELECT order_id,sum(price_unit*qty*discount/100) amount FROM pos_order_line GROUP BY order_id)
   SELECT j.id,j.id job_id,j.name,j.earlydryer_branch_id,j.company_id,j.partner_id,j.channel,j.express,j.fulfilment,j.state,
    j.received_on,(j.received_on AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date received_date,
    j.ready_on,(j.ready_on AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date ready_date,
    j.closed_on,(j.closed_on AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date closed_date,
    coalesce(i.item_count,0)::integer item_count,
    CASE WHEN j.sale_order_id IS NOT NULL THEN coalesce(s.amount_total,0)
         WHEN j.pos_order_id IS NOT NULL THEN coalesce(p.amount_total,0)-CASE WHEN p.state IN ('paid','done') THEN coalesce(ps.amount,0) ELSE 0 END
         ELSE 0 END amount_total,
    CASE WHEN j.sale_order_id IS NOT NULL THEN coalesce(d.amount,0) ELSE coalesce(pd.amount,0) END discount_amount,
    greatest(extract(epoch FROM(j.ready_on-j.received_on))/3600,0) turnaround_hours,
    (j.ready_on IS NOT NULL AND j.promised_on IS NOT NULL AND j.ready_on<=j.promised_on) on_time,
    (j.state NOT IN ('delivered','collected','cancelled','uncollected','ready','out_for_delivery') AND j.promised_on<(now() AT TIME ZONE 'UTC')) is_overdue,
    j.earlydryer_released_unpaid released_unpaid,
    (j.id=first_customer.first_id) is_first_job,
    (first_customer.first_received_on AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date first_received_date,
    coalesce(i.rework_items_count,0)::integer rework_items_count
   FROM laundry_job j LEFT JOIN first_customer ON first_customer.company_id=j.company_id AND first_customer.partner_id=j.partner_id LEFT JOIN items i ON i.job_id=j.id
   LEFT JOIN sale_order s ON s.id=j.sale_order_id LEFT JOIN pos_order p ON p.id=j.pos_order_id
   LEFT JOIN pos_settlements ps ON ps.order_id=p.id LEFT JOIN discounts d ON d.order_id=s.id
   LEFT JOIN pos_discounts pd ON pd.order_id=p.id WHERE j.state!='cancelled'""")
        )
        self.env.cr.execute(
            SQL(
                "CREATE INDEX IF NOT EXISTS earlydryer_reporting_job_branch_received ON laundry_job(earlydryer_branch_id,received_on)"
            )
        )
        self.env.cr.execute(
            SQL(
                "CREATE INDEX IF NOT EXISTS earlydryer_reporting_job_partner_received ON laundry_job(company_id,partner_id,received_on,id)"
            )
        )
