# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain


class EarlydryerWhtReportWizard(models.TransientModel):
    """WHT withheld from vendors over a period: PDF, XLSX, and the remittance."""

    _name = "earlydryer.wht.report.wizard"
    _description = "Earlydryer WHT Remittance Report"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_range_id = fields.Many2one("date.range", string="Period")
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1)
        - relativedelta(months=1),
    )
    date_to = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1)
        - relativedelta(days=1),
    )
    only_unremitted = fields.Boolean(
        string="Not Remitted Only",
        default=True,
        help="Leave out the WHT already paid to the tax authority.",
    )
    line_ids = fields.Many2many(
        "account.move.line", compute="_compute_lines", string="WHT Lines"
    )
    total_base = fields.Monetary(compute="_compute_lines", string="Gross Amount")
    total_wht = fields.Monetary(compute="_compute_lines", string="WHT Amount")

    @api.onchange("date_range_id")
    def _onchange_date_range_id(self):
        if self.date_range_id:
            self.date_from = self.date_range_id.date_start
            self.date_to = self.date_range_id.date_end

    @api.model
    def _earlydryer_check_right(self):
        user = self.env.user
        if self.env.su or user.has_group("earlydryer_base.group_finance"):
            return True
        raise AccessError(self.env._("The WHT reports are for Finance."))

    @api.model_create_multi
    def create(self, vals_list):
        self._earlydryer_check_right()
        return super().create(vals_list)

    def _earlydryer_domain(self):
        self.ensure_one()
        domain = Domain(
            [
                ("company_id", "=", self.company_id.id),
                ("tax_line_id.earlydryer_wht_category_id", "!=", False),
                ("parent_state", "=", "posted"),
                ("date", ">=", self.date_from),
                ("date", "<=", self.date_to),
            ]
        )
        if self.only_unremitted:
            domain &= Domain("reconciled", "=", False)
        return domain

    @api.depends("date_from", "date_to", "only_unremitted", "company_id")
    def _compute_lines(self):
        MoveLine = self.env["account.move.line"].sudo()
        for wizard in self:
            lines = MoveLine.search(wizard._earlydryer_domain(), order="date, id")
            wizard.line_ids = lines
            rows = wizard._earlydryer_rows(lines)
            wizard.total_base = sum(row["base"] for row in rows)
            wizard.total_wht = sum(row["wht"] for row in rows)

    def _earlydryer_rows(self, lines=None):
        """Report rows: one per WHT tax line (credit notes are negative)."""
        self.ensure_one()
        if lines is None:
            lines = self.line_ids
        rows = []
        for line in lines.sudo():
            move = line.move_id
            partner = (line.partner_id or move.partner_id).commercial_partner_id
            sign = -1 if move.move_type == "in_refund" else 1
            tax = line.tax_line_id
            rows.append(
                {
                    "line": line,
                    "vendor": partner.display_name,
                    "tin": partner.vat or "",
                    "invoice": move.ref or move.name,
                    "number": move.name,
                    "date": move.invoice_date or move.date,
                    "base": sign * abs(line.tax_base_amount),
                    "rate": abs(tax.amount),
                    "wht": -line.balance,
                    "category": tax.earlydryer_wht_category_id.name,
                    "vendor_type": dict(
                        tax._fields["earlydryer_wht_vendor_type"]._description_selection(
                            self.env
                        )
                    ).get(tax.earlydryer_wht_vendor_type, ""),
                }
            )
        return rows

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            "earlydryer_accounting_ng.action_report_wht_remittance"
        ).report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        return self.env.ref(
            "earlydryer_accounting_ng.action_report_wht_remittance_xlsx"
        ).report_action(self)

    def action_view_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("WHT Lines"),
            "res_model": "account.move.line",
            "view_mode": "list,form",
            "domain": [("id", "in", self.line_ids.ids)],
        }

    def action_mark_remitted(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: not line.reconciled)
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Mark WHT Remitted"),
            "res_model": "earlydryer.wht.remit.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_company_id": self.company_id.id,
                "default_line_ids": [(6, 0, lines.ids)],
                "default_date_from": fields.Date.to_string(self.date_from),
                "default_date_to": fields.Date.to_string(self.date_to),
            },
        }
