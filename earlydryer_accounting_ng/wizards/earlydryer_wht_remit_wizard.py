# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError


class EarlydryerWhtRemitWizard(models.TransientModel):
    """Pay the WHT of a period to the tax authority and reconcile the WHT
    payable lines with the payment."""

    _name = "earlydryer.wht.remit.wizard"
    _description = "Mark WHT Remitted"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    line_ids = fields.Many2many("account.move.line", string="WHT Lines")
    date_from = fields.Date()
    date_to = fields.Date()
    date = fields.Date(
        string="Payment Date", required=True, default=fields.Date.context_today
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Paid From",
        required=True,
        domain="[('company_id', '=', company_id), ('type', '=', 'bank'), "
        "('earlydryer_role', 'in', (False, 'bank'))]",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Tax Authority",
        required=True,
        default=lambda self: self.env.company.earlydryer_tax_authority_id,
    )
    reference = fields.Char(help="Receipt or remittance reference of the tax authority.")
    amount = fields.Monetary(compute="_compute_amount")

    @api.depends("line_ids")
    def _compute_amount(self):
        for wizard in self:
            wizard.amount = -sum(wizard.line_ids.mapped("balance"))

    @api.model_create_multi
    def create(self, vals_list):
        self.env["earlydryer.wht.report.wizard"]._earlydryer_check_right()
        return super().create(vals_list)

    def _earlydryer_outstanding_account(self):
        self.ensure_one()
        method_lines = self.journal_id.outbound_payment_method_line_ids
        account = method_lines.payment_account_id[:1]
        if not account:
            account = self.env["account.payment"].with_company(self.company_id).new(
                {"journal_id": self.journal_id.id}
            )._get_outstanding_account("outbound")
        return account

    def action_remit(self):
        """Outbound payment to the tax authority, destination WHT payable,
        reconciled with the WHT lines."""
        self.ensure_one()
        self.env["earlydryer.wht.report.wizard"]._earlydryer_check_right()
        company = self.company_id
        account = company.earlydryer_wht_payable_account_id
        lines = self.line_ids.sudo().filtered(
            lambda line: not line.reconciled and line.account_id == account
        )
        if not lines:
            raise UserError(self.env._("There is no WHT left to remit in this period."))
        amount = -sum(lines.mapped("balance"))
        if company.currency_id.compare_amounts(amount, 0) <= 0:
            raise UserError(self.env._("The WHT to remit must be positive."))
        memo = self.reference or self.env._(
            "WHT remittance %(start)s - %(end)s",
            start=self.date_from or "",
            end=self.date_to or "",
        )
        payment = (
            self.env["account.payment"]
            .sudo()
            .create(
                {
                    "payment_type": "outbound",
                    "partner_type": "supplier",
                    "partner_id": self.partner_id.id,
                    "amount": amount,
                    "date": self.date,
                    "journal_id": self.journal_id.id,
                    "company_id": company.id,
                    "memo": memo,
                    "destination_account_id": account.id,
                    "force_outstanding_account_id": (
                        self._earlydryer_outstanding_account().id
                    ),
                }
            )
        )
        payment.action_post()
        payment.move_id.earlydryer_kind = "wht_remittance"
        counterpart = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == account
        )
        (counterpart | lines).reconcile()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "res_id": payment.id,
            "view_mode": "form",
        }
