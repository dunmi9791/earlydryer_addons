# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    earlydryer_rider_short_mode = fields.Selection(
        [
            ("rider_receivable", "Rider Receivable"),
            ("cash_short", "Cash Over and Short"),
        ],
        string="Rider Cash Shortage",
        default="rider_receivable",
        required=True,
        help="Where a shortage found when closing a trip is posted. It is "
        "never written off silently: the manager is alerted either way.",
    )
    earlydryer_rider_receivable_account_id = fields.Many2one(
        "account.account",
        string="Rider Receivable Account",
        check_company=True,
        help="Debited with rider shortages (default: the receivable account "
        "of the rider's contact).",
    )
    earlydryer_carrier_expense_account_id = fields.Many2one(
        "account.account",
        string="3PL Delivery Expense Account",
        check_company=True,
        help="Expense of carrier bills (default: the company's expense account).",
    )
