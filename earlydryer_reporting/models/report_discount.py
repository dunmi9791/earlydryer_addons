# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models, tools
from odoo.tools import SQL


class ReportDiscount(models.Model):
    _name = "earlydryer.report.discount"
    _description = "Earlydryer Commercial Discounts"
    _auto = False
    earlydryer_branch_id = fields.Many2one("earlydryer.branch", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    date = fields.Date(readonly=True)
    product_id = fields.Many2one("product.product", readonly=True)
    origin = fields.Char(readonly=True)
    gross = fields.Float(readonly=True)
    discount = fields.Float(readonly=True)
    net = fields.Float(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        linked = (
            SQL(
                "AND NOT EXISTS(SELECT 1 FROM pos_order_line pl WHERE pl.sale_order_line_id=l.id)"
            )
            if "sale_order_line_id" in self.env["pos.order.line"]._fields
            else SQL("")
        )
        self.env.cr.execute(
            SQL(
                """CREATE VIEW earlydryer_report_discount AS
   SELECT l.id,c.earlydryer_branch_id,o.company_id,(o.date_order AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date date,l.product_id,'pos'::varchar origin,
    l.qty*l.price_unit gross,l.qty*l.price_unit*l.discount/100 discount,l.price_subtotal net FROM pos_order_line l
   JOIN pos_order o ON o.id=l.order_id JOIN pos_config c ON c.id=o.config_id WHERE o.state IN ('paid','done','invoiced')
   UNION ALL SELECT -l.id,o.earlydryer_branch_id,o.company_id,(o.date_order AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Lagos')::date,l.product_id,'sale',
    l.product_uom_qty*l.price_unit,l.product_uom_qty*l.price_unit*l.discount/100,l.price_subtotal
   FROM sale_order_line l JOIN sale_order o ON o.id=l.order_id WHERE o.state='sale' %s""",
                linked,
            )
        )
