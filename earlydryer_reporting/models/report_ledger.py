# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models, tools
from odoo.tools import SQL


class ReportLedger(models.Model):
    _name = "earlydryer.report.ledger"
    _description = "Earlydryer Posted Plant Analytic Allocation"
    _auto = False
    line_id = fields.Many2one("account.move.line", readonly=True)
    earlydryer_branch_id = fields.Many2one("earlydryer.branch", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    date = fields.Date(readonly=True)
    account_id = fields.Many2one("account.account", readonly=True)
    account_type = fields.Char(readonly=True)
    account_name = fields.Char(readonly=True)
    amount = fields.Float(readonly=True)
    balance = fields.Float(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            SQL("""CREATE VIEW earlydryer_report_ledger AS
            SELECT row_number() OVER(ORDER BY l.id,b.id)::integer id,l.id line_id,b.id earlydryer_branch_id,
            l.company_id,l.date,l.account_id,a.account_type,coalesce(a.name->>'en_US',a.name::text) account_name,
            sum(l.balance*dist.value::numeric/100) balance,
            sum(l.balance*dist.value::numeric/100)*CASE WHEN a.account_type IN ('income','income_other') THEN -1 ELSE 1 END amount
            FROM account_move_line l JOIN account_account a ON a.id=l.account_id
            CROSS JOIN LATERAL jsonb_each_text(coalesce(l.analytic_distribution,'{}'::jsonb)) dist
            JOIN earlydryer_branch b ON b.analytic_account_id::text=ANY(string_to_array(dist.key,','))
            WHERE l.company_id=b.company_id AND l.parent_state='posted'
            AND a.account_type IN ('income','income_other','expense','expense_direct_cost','expense_depreciation')
            GROUP BY l.id,b.id,a.account_type,a.name""")
        )
