# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

CHECK_CODES = [
    ("pos_closed", "All POS sessions closed"),
    ("bank_reconciled", "Bank statements imported and reconciled"),
    ("clearing_reconciled", "Card and gateway clearing accounts reconciled"),
    ("wallet_control", "Wallet control difference zero"),
    ("analytic_gaps", "Analytic gaps empty"),
    ("wht_prepared", "WHT remittance prepared"),
    ("depreciation", "Depreciation posted"),
    ("vat_return", "VAT return prepared"),
    ("lock_date", "Lock date set"),
    ("manual", "Manual check"),
]


class EarlydryerCloseChecklistItem(models.Model):
    """A step of the month-end close, copied on each period's checklist."""

    _name = "earlydryer.close.checklist.item"
    _description = "Earlydryer Month-end Checklist Step"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    check_code = fields.Selection(
        CHECK_CODES,
        required=True,
        default="manual",
        help="Steps other than Manual have a Check button computing their status.",
    )
    description = fields.Text(translate=True)
