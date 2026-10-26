# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class EarlydryerCashLodgementWizard(models.TransientModel):
    """End-of-day lodgement: plant cash → cash in transit to bank. The bank
    statement line, imported later, is reconciled with cash in transit."""

    _name = "earlydryer.cash.lodgement.wizard"
    _description = "Earlydryer Cash Lodgement"

    branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        required=True,
        default=lambda self: self.env[
            "earlydryer.branch.mixin"
        ]._default_earlydryer_branch_id(),
    )
    company_id = fields.Many2one(related="branch_id.company_id")
    currency_id = fields.Many2one(related="branch_id.currency_id")
    date = fields.Date(required=True, default=fields.Date.context_today)
    cash_journal_id = fields.Many2one(related="branch_id.cash_journal_id")
    cash_balance = fields.Monetary(
        compute="_compute_cash_balance",
        string="Cash in the Plant Journal",
        help="Posted balance of the plant cash account at the end of the date.",
    )
    float_amount = fields.Monetary(
        string="Float Kept",
        compute="_compute_float_amount",
        store=True,
        readonly=False,
    )
    amount = fields.Monetary(
        string="Amount Lodged",
        compute="_compute_amount",
        store=True,
        readonly=False,
        help="Default: the balance minus the float.",
    )
    bank_journal_id = fields.Many2one(
        "account.journal",
        string="Bank",
        required=True,
        domain="[('company_id', '=', company_id), ('type', '=', 'bank'), "
        "('earlydryer_role', 'in', (False, 'bank'))]",
        default=lambda self: self.env["account.journal"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("earlydryer_role", "=", "bank"),
            ],
            limit=1,
        ),
    )
    reference = fields.Char(string="Teller / Slip Reference")
    below_float = fields.Boolean(compute="_compute_below_float")

    @api.depends("branch_id", "date")
    def _compute_cash_balance(self):
        for wizard in self:
            wizard.cash_balance = (
                wizard.branch_id.sudo()._earlydryer_cash_balance(wizard.date)
                if wizard.branch_id and wizard.date
                else 0.0
            )

    @api.depends("branch_id")
    def _compute_float_amount(self):
        for wizard in self:
            wizard.float_amount = wizard.branch_id.sudo().earlydryer_cash_float

    @api.depends("cash_balance", "float_amount")
    def _compute_amount(self):
        for wizard in self:
            wizard.amount = max(wizard.cash_balance - wizard.float_amount, 0.0)

    @api.depends("cash_balance", "amount", "branch_id")
    def _compute_below_float(self):
        for wizard in self:
            left = wizard.cash_balance - wizard.amount
            wizard.below_float = (
                wizard.currency_id.compare_amounts(
                    left, wizard.branch_id.sudo().earlydryer_cash_float
                )
                < 0
                if wizard.currency_id
                else False
            )

    def action_lodge(self):
        self.ensure_one()
        return self._earlydryer_lodge()

    def _earlydryer_lodge(self):
        """Post the lodgement entry. Rights are checked here (the entry is
        created with sudo)."""
        self.ensure_one()
        branch = self.branch_id
        branch._earlydryer_check_cash_right("lodge")
        if self.below_float:
            branch._earlydryer_check_cash_right("below_float")
        branch = branch.sudo()
        company = branch.company_id
        transit = company.earlydryer_cash_transit_account_id
        journal = branch.cash_journal_id
        if not transit or not journal:
            raise UserError(
                self.env._("Run the accounting setup first (plant cash, cash in transit).")
            )
        if company.currency_id.compare_amounts(self.amount, 0) <= 0:
            raise UserError(self.env._("The amount lodged must be positive."))
        label = self.env._(
            "Lodgement %(plant)s to %(bank)s",
            plant=branch.code,
            bank=self.bank_journal_id.sudo().name,
        )
        move = (
            self.env["account.move"]
            .sudo()
            .create(
                {
                    "move_type": "entry",
                    "journal_id": journal.id,
                    "date": self.date,
                    "ref": " - ".join(part for part in (label, self.reference) if part),
                    "earlydryer_branch_id": branch.id,
                    "earlydryer_kind": "lodgement",
                    "earlydryer_lodgement_journal_id": self.bank_journal_id.id,
                    "line_ids": [
                        Command.create(
                            {
                                "name": self.reference or label,
                                "account_id": transit.id,
                                "debit": self.amount,
                            }
                        ),
                        Command.create(
                            {
                                "name": label,
                                "account_id": journal.default_account_id.id,
                                "credit": self.amount,
                            }
                        ),
                    ],
                }
            )
        )
        move.action_post()
        if self.below_float:
            move.message_post(
                body=self.env._(
                    "Lodged below the float of %(float)s, by %(user)s.",
                    float=company.currency_id.format(branch.earlydryer_cash_float),
                    user=self.env.user.name,
                )
            )
        return move
