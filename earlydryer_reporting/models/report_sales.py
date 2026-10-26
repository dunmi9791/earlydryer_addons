# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models, tools
from odoo.tools import SQL


class ReportSales(models.Model):
    _name = "earlydryer.report.sales"
    _description = "Earlydryer Operational Sales (Not Posted Revenue)"
    _auto = False
    earlydryer_branch_id = fields.Many2one("earlydryer.branch", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    date = fields.Date(readonly=True)
    product_id = fields.Many2one("product.product", readonly=True)
    product_kind = fields.Char(readonly=True)
    service_line_id = fields.Many2one("account.analytic.account", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    channel = fields.Char(readonly=True)
    origin = fields.Char(readonly=True)
    quantity = fields.Float(readonly=True)
    gross = fields.Float(readonly=True)
    discount = fields.Float(readonly=True)
    net = fields.Float(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            SQL("""CREATE VIEW earlydryer_report_sales AS
   SELECT l.id,c.earlydryer_branch_id,o.company_id,(o.date_order AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date date,
   l.product_id,t.earlydryer_kind product_kind,t.earlydryer_service_line_id service_line_id,o.partner_id,'pos'::varchar channel,'pos'::varchar origin,
   l.qty quantity,l.qty*l.price_unit gross,l.qty*l.price_unit*l.discount/100 discount,l.price_subtotal net
   FROM pos_order_line l JOIN pos_order o ON o.id=l.order_id JOIN pos_config c ON c.id=o.config_id
   JOIN product_product p ON p.id=l.product_id JOIN product_template t ON t.id=p.product_tmpl_id WHERE o.state IN ('paid','done','invoiced')
   UNION ALL
   SELECT -l.id,l.earlydryer_branch_id,l.company_id,coalesce(m.invoice_date,m.date),l.product_id,t.earlydryer_kind,t.earlydryer_service_line_id,m.partner_id,'invoice','invoice',
   l.quantity*CASE WHEN m.move_type='out_refund' THEN -1 ELSE 1 END,
   l.quantity*l.price_unit*CASE WHEN m.move_type='out_refund' THEN -1 ELSE 1 END,
   l.quantity*l.price_unit*l.discount/100*CASE WHEN m.move_type='out_refund' THEN -1 ELSE 1 END,
   l.price_subtotal*CASE WHEN m.move_type='out_refund' THEN -1 ELSE 1 END
   FROM account_move_line l JOIN account_move m ON m.id=l.move_id JOIN product_product p ON p.id=l.product_id
   JOIN product_template t ON t.id=p.product_tmpl_id WHERE m.state='posted' AND m.move_type IN ('out_invoice','out_refund')
   AND l.display_type='product' AND NOT EXISTS(SELECT 1 FROM pos_order po WHERE po.account_move=m.id)""")
        )
