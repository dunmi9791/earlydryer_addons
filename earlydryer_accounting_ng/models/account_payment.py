# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    earlydryer_wht_amount = fields.Monetary(
        string="WHT Deducted",
        compute="_compute_earlydryer_wht_amount",
        currency_field="company_currency_id",
        help="Withholding tax kept from the vendor on the bills this payment pays "
        "(the vendor is paid net; the WHT goes to the tax authority).",
    )
    earlydryer_wht_bill_ids = fields.Many2many(
        "account.move",
        string="Bills with WHT",
        compute="_compute_earlydryer_wht_amount",
    )

    @api.depends("invoice_ids", "reconciled_bill_ids")
    def _compute_earlydryer_wht_amount(self):
        for payment in self:
            bills = (payment.invoice_ids | payment.reconciled_bill_ids).filtered(
                lambda move: (
                    move.move_type in ("in_invoice", "in_refund")
                    and move.earlydryer_wht_amount
                )
            )
            payment.earlydryer_wht_bill_ids = bills
            payment.earlydryer_wht_amount = sum(
                bill.earlydryer_wht_amount
                * (-1 if bill.move_type == "in_refund" else 1)
                for bill in bills
            )
