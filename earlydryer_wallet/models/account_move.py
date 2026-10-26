# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    earlydryer_wallet_transaction_ids = fields.One2many(
        "earlydryer.wallet.transaction",
        "invoice_id",
        string="Wallet Spends",
        readonly=True,
    )
    earlydryer_wallet_balance = fields.Monetary(
        string="Wallet Balance",
        compute="_compute_earlydryer_wallet_balance",
        compute_sudo=True,
    )
    earlydryer_wallet_can_pay = fields.Boolean(
        compute="_compute_earlydryer_wallet_balance", compute_sudo=True
    )

    @api.depends("partner_id", "amount_residual", "state", "move_type")
    def _compute_earlydryer_wallet_balance(self):
        Wallet = self.env["earlydryer.wallet"]
        for move in self:
            wallet = (
                Wallet._earlydryer_get(move.partner_id, move.company_id)
                if move.partner_id and move.move_type == "out_invoice"
                else Wallet
            )
            balance = wallet.balance if wallet else 0.0
            move.earlydryer_wallet_balance = balance
            move.earlydryer_wallet_can_pay = bool(
                wallet
                and wallet.state == "active"
                and move.state == "posted"
                and move.move_type == "out_invoice"
                and move.currency_id == move.company_id.currency_id
                and move.currency_id.compare_amounts(move.amount_residual, 0.0) > 0
                and move.currency_id.compare_amounts(balance, 0.0) > 0
            )

    def action_earlydryer_wallet_pay(self):
        self.ensure_one()
        self.env["earlydryer.wallet"]._earlydryer_check_right("spend")
        if not self.earlydryer_wallet_can_pay:
            raise UserError(
                self.env._(
                    "Nothing to pay from the wallet on %(move)s.", move=self.name
                )
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Pay from Wallet"),
            "res_model": "earlydryer.wallet.spend.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_invoice_id": self.id},
        }

    # ------------------------------------------------------------------
    # Wallet spending
    # ------------------------------------------------------------------

    def _earlydryer_wallet_spend(self, amount, laundry_job=None, branch=None):
        """Spend ``amount`` of the customer's wallet on this posted invoice."""
        self.ensure_one()
        if self.move_type != "out_invoice" or self.state != "posted":
            raise UserError(
                self.env._("Only posted customer invoices are paid from a wallet.")
            )
        currency = self.currency_id
        if currency != self.company_id.currency_id:
            raise UserError(self.env._("Wallets pay invoices in the company currency."))
        if currency.compare_amounts(amount, self.amount_residual) > 0:
            raise UserError(
                self.env._(
                    "%(move)s has only %(residual)s left to pay.",
                    move=self.name,
                    residual=self.amount_residual,
                )
            )
        branch = branch or (laundry_job.earlydryer_branch_id if laundry_job else None)
        tx = self.env["earlydryer.wallet.transaction"]._earlydryer_new(
            self.partner_id,
            "spend",
            amount,
            company=self.company_id,
            invoice_id=self.id,
            laundry_job_id=laundry_job.id if laundry_job else False,
            earlydryer_branch_id=(branch or self.env.user.earlydryer_branch_id).id,
            reference=self.name,
        )
        tx.action_post()
        return tx

    def _earlydryer_wallet_auto_apply_ok(self):
        """Invoices from sales orders (laundry jobs are invoiced through them),
        never POS invoices: the till handles its own wallet payments."""
        self.ensure_one()
        return (
            self.move_type == "out_invoice"
            and self.state == "posted"
            and self.company_id.earlydryer_wallet_auto_apply
            and not self.pos_order_ids
            and bool(self.invoice_line_ids.sale_line_ids)
        )

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted.filtered(
            lambda move: (
                move.move_type == "out_invoice"
                and move.company_id.earlydryer_wallet_auto_apply
            )
        ):
            if move._earlydryer_wallet_auto_apply_ok():
                move._earlydryer_wallet_auto_apply()
        return posted

    def _earlydryer_wallet_auto_apply(self):
        """Spend the available balance on this invoice; never blocks posting."""
        self.ensure_one()
        wallet = self.env["earlydryer.wallet"]._earlydryer_get(
            self.partner_id, self.company_id
        )
        if not wallet or wallet.sudo().state != "active":
            return False
        amount = min(wallet.sudo().balance, self.amount_residual)
        if self.currency_id.compare_amounts(amount, 0.0) <= 0:
            return False
        jobs = self.invoice_line_ids.sale_line_ids.order_id.laundry_job_ids
        try:
            with self.env.cr.savepoint():
                self.sudo()._earlydryer_wallet_spend(amount, laundry_job=jobs[:1])
        except UserError as error:
            _logger.warning("Wallet not applied to %s: %s", self.name, error)
            return False
        return True
