# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

JOURNAL_ROLES = [
    ("plant_cash", "Plant Cash"),
    ("rider_cash", "Rider Cash"),
    ("card", "Card Terminal Clearing"),
    ("bank", "Bank Account"),
    ("gateway", "Payment Gateway Clearing"),
    ("opening", "Opening Balances"),
]


class AccountJournal(models.Model):
    _inherit = "account.journal"

    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        index="btree_not_null",
        check_company=True,
        ondelete="restrict",
        help="Set on the plant's cash and rider cash journals. Empty on the "
        "company-wide journals (bank, card, gateway): one real account serves "
        "both plants, and plant reporting comes from the analytics.",
    )
    earlydryer_role = fields.Selection(
        JOURNAL_ROLES,
        string="Earlydryer Role",
        index="btree_not_null",
        help="Set by the accounting setup wizard.",
    )
    earlydryer_show_on_invoice = fields.Boolean(
        string="Show on Invoices",
        help="Print this bank account on customer invoices for transfer payments.",
    )
