# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class EarlydryerWhtDeductionWizard(models.TransientModel):
    """A corporate customer deducted WHT from an Earlydryer invoice:
    Dr WHT receivable / Cr Receivable, reconciled with the invoice."""

    _name = "earlydryer.wht.deduction.wizard"
    _description = "Register WHT Deduction"

    invoice_id = fields.Many2one(
        "account.move",
        required=True,
        domain=[("move_type", "=", "out_invoice"), ("state", "=", "posted")],
    )
    company_id = fields.Many2one(related="invoice_id.company_id")
    currency_id = fields.Many2one(related="company_id.currency_id")
    partner_id = fields.Many2one(related="invoice_id.commercial_partner_id")
    amount_residual = fields.Monetary(related="invoice_id.amount_residual")
    rate = fields.Float(
        string="Rate (%)",
        digits=(5, 2),
        help="Fills the amount from the untaxed total of the invoice.",
    )
    amount = fields.Monetary(required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    reference = fields.Char(
        string="Credit Note / Certificate Ref.",
        help="The customer's WHT credit note or certificate reference.",
    )
    certificate_date = fields.Date(
        string="Certificate Received On",
        help="Leave empty while the certificate is awaited.",
    )

    @api.onchange("rate")
    def _onchange_rate(self):
        if self.rate and self.invoice_id:
            self.amount = self.currency_id.round(
                self.invoice_id.amount_untaxed * self.rate / 100.0
            )

    @api.model_create_multi
    def create(self, vals_list):
        self.env["earlydryer.wht.report.wizard"]._earlydryer_check_right()
        return super().create(vals_list)

    def action_register(self):
        self.ensure_one()
        self.env["earlydryer.wht.report.wizard"]._earlydryer_check_right()
        invoice = self.invoice_id.sudo()
        company = invoice.company_id
        account = company.earlydryer_wht_receivable_account_id
        if not account:
            raise UserError(
                self.env._("Run the accounting setup first (WHT receivable).")
            )
        if company.currency_id.compare_amounts(self.amount, 0) <= 0:
            raise UserError(self.env._("The WHT amount must be positive."))
        if (
            company.currency_id.compare_amounts(self.amount, invoice.amount_residual)
            > 0
        ):
            raise UserError(
                self.env._("The WHT cannot be more than the amount due on the invoice.")
            )
        receivable = invoice.line_ids.filtered(
            lambda line: (
                line.account_id.account_type == "asset_receivable"
                and not line.reconciled
            )
        )
        partner = invoice.commercial_partner_id
        label = self.env._(
            "WHT deducted by customer on %(invoice)s", invoice=invoice.name
        )
        journal = company._earlydryer_misc_journal()
        move = (
            self.env["account.move"]
            .sudo()
            .create(
                {
                    "move_type": "entry",
                    "journal_id": journal.id,
                    "date": self.date,
                    "ref": " - ".join(part for part in (label, self.reference) if part),
                    "earlydryer_kind": "wht_deduction",
                    "earlydryer_wht_invoice_id": invoice.id,
                    "earlydryer_wht_reference": self.reference,
                    "earlydryer_wht_certificate_date": self.certificate_date,
                    "earlydryer_branch_id": invoice.earlydryer_branch_id.id,
                    "line_ids": [
                        Command.create(
                            {
                                "name": label,
                                "account_id": account.id,
                                "partner_id": partner.id,
                                "debit": self.amount,
                            }
                        ),
                        Command.create(
                            {
                                "name": label,
                                "account_id": receivable[:1].account_id.id,
                                "partner_id": partner.id,
                                "credit": self.amount,
                            }
                        ),
                    ],
                }
            )
        )
        move.action_post()
        credit = move.line_ids.filtered(
            lambda line: line.account_id == receivable[:1].account_id
        )
        (credit | receivable).reconcile()
        invoice.message_post(
            body=self.env._(
                "WHT of %(amount)s deducted by the customer (%(ref)s): %(move)s.",
                amount=company.currency_id.format(self.amount),
                ref=self.reference or self.env._("no reference"),
                move=move.name,
            )
        )
        return {"type": "ir.actions.act_window_close"}
