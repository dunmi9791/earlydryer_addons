# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError


class LaundryJob(models.Model):
    _inherit = "laundry.job"

    earlydryer_wallet_transaction_ids = fields.One2many(
        "earlydryer.wallet.transaction",
        "laundry_job_id",
        string="Wallet Transactions",
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

    @api.depends("partner_id")
    def _compute_earlydryer_wallet_balance(self):
        Wallet = self.env["earlydryer.wallet"]
        for job in self:
            company = job.company_id or self.env.company
            wallet = Wallet._earlydryer_get(job.partner_id, company)
            balance = wallet.balance if wallet else 0.0
            currency = job.currency_id or company.currency_id
            job.earlydryer_wallet_balance = balance
            job.earlydryer_wallet_can_pay = bool(
                wallet
                and wallet.state == "active"
                and job.state != "cancelled"
                and currency.compare_amounts(balance, 0.0) > 0
                and currency.compare_amounts(job.amount_due, 0.0) > 0
            )

    def _earlydryer_extra_paid(self):
        """Wallet spends on this job not yet reconciled with its receivable.

        A spend is reconciled with the job's invoice (sales flow) or its POS
        receivable at once, which already lowers the due amount: those count
        nothing here. Only a spend on a POS job whose session is still open
        waits for the closing entry; its open receivable credit counts as paid
        until the closing reconciles it.
        """
        paid = super()._earlydryer_extra_paid()
        spends = self.sudo().earlydryer_wallet_transaction_ids.filtered(
            lambda tx: tx.type == "spend" and tx.state == "posted" and tx.move_id
        )
        for tx in spends:
            paid -= sum(tx._earlydryer_receivable_credit().mapped("amount_residual"))
        return paid

    def _earlydryer_wallet_invoice(self):
        """Open customer invoice of the job (sales flow or invoiced POS order)."""
        self.ensure_one()
        job = self.sudo()
        invoices = job.sale_order_id.invoice_ids | job.pos_order_id.account_move
        return invoices.filtered(
            lambda move: (
                move.move_type == "out_invoice"
                and move.state == "posted"
                and move.currency_id.compare_amounts(move.amount_residual, 0.0) > 0
            )
        ).sorted(lambda move: (move.invoice_date or move.date, move.id))[:1]

    def _earlydryer_wallet_spend(self, amount):
        """Pay ``amount`` of this job from the customer's wallet."""
        self.ensure_one()
        Wallet = self.env["earlydryer.wallet"]
        Wallet._earlydryer_check_right("spend")
        currency = self.currency_id
        if currency.compare_amounts(amount, self.amount_due) > 0:
            raise UserError(
                self.env._(
                    "Only %(due)s is due on %(job)s.",
                    due=self._earlydryer_format_amount(self.amount_due),
                    job=self.name,
                )
            )
        invoice = self._earlydryer_wallet_invoice()
        if invoice:
            return invoice._earlydryer_wallet_spend(amount, laundry_job=self)
        if not self.pos_order_id:
            raise UserError(
                self.env._(
                    "Invoice the sales order of %(job)s first: the wallet pays its "
                    "invoice.",
                    job=self.name,
                )
            )
        # POS job on the customer account: Cr receivable, reconciled with the
        # order's pay-later receivable now (session closed) or at closing
        tx = self.env["earlydryer.wallet.transaction"]._earlydryer_new(
            self.partner_id,
            "spend",
            amount,
            company=self.company_id,
            laundry_job_id=self.id,
            earlydryer_branch_id=self.earlydryer_branch_id.id,
            reference=self.name,
        )
        tx.action_post()
        return tx

    def action_earlydryer_wallet_pay(self):
        self.ensure_one()
        self.env["earlydryer.wallet"]._earlydryer_check_right("spend")
        if not self.earlydryer_wallet_can_pay:
            raise UserError(
                self.env._("Nothing to pay from the wallet on %(job)s.", job=self.name)
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Pay from Wallet"),
            "res_model": "earlydryer.wallet.spend.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_laundry_job_id": self.id},
        }
