# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

TODO_ACTIVITY = "mail.mail_activity_data_todo"


class PosOrder(models.Model):
    _inherit = "pos.order"

    earlydryer_wallet_balance_after = fields.Float(
        string="Wallet Balance after Sale",
        readonly=True,
        copy=False,
        help="Balance printed on the receipt, as known by the till at the time "
        "of sale.",
    )
    earlydryer_wallet_transaction_ids = fields.One2many(
        "earlydryer.wallet.transaction",
        "pos_order_id",
        string="Wallet Transactions",
        readonly=True,
    )
    earlydryer_wallet_error = fields.Text(
        string="Wallet Sync Error",
        readonly=True,
        copy=False,
        help="Set when the wallet transactions of this order could not be "
        "recorded at sync. The sale itself is saved.",
    )

    # ------------------------------------------------------------------
    # Amounts: wallet payments are paid, not a balance on account
    # ------------------------------------------------------------------

    def _earlydryer_pay_later_amount(self):
        self.ensure_one()
        return sum(
            payment.amount
            for payment in self.payment_ids
            if payment.payment_method_id.type == "pay_later"
            and not payment.payment_method_id.earlydryer_is_wallet
        )

    def _earlydryer_wallet_paid(self):
        self.ensure_one()
        return sum(
            payment.amount
            for payment in self.payment_ids
            if payment.payment_method_id.earlydryer_is_wallet
        )

    def _earlydryer_wallet_topup_amount(self):
        """Top-up lines of this order (not part of any laundry job)."""
        self.ensure_one()
        return sum(
            self.lines.filtered(
                lambda line: line.product_id.earlydryer_kind == "wallet_topup"
            ).mapped("price_subtotal_incl")
        )

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def _process_saved_order(self, draft):
        res = super()._process_saved_order(draft)
        if not draft and self.state in ("paid", "done"):
            self._earlydryer_wallet_sync()
        return res

    def _earlydryer_wallet_sync(self):
        """Wallet transactions of a synced order, in a savepoint: a failure
        never loses the sale (stored on the order, Finance told)."""
        self.ensure_one()
        if (
            not self._earlydryer_wallet_lines()
            and not self._earlydryer_wallet_payments()
        ):
            return True
        try:
            with self.env.cr.savepoint():
                self._earlydryer_wallet_record()
        except Exception as error:  # pylint: disable=broad-except
            _logger.exception("Wallet sync failed for POS order %s", self.name)
            message = str(error) or error.__class__.__name__
            order = self.sudo()
            order.earlydryer_wallet_error = message
            order.message_post(
                body=self.env._(
                    "The wallet transactions could not be recorded: %(error)s. "
                    "Use Retry Wallet Sync once the cause is fixed.",
                    error=message,
                ),
                subtype_xmlid="mail.mt_note",
            )
            users = self.env["earlydryer.wallet.transaction"]._earlydryer_finance_users(
                order.company_id
            )
            for user in users | order.config_id._earlydryer_manager_users():
                order.activity_schedule(
                    TODO_ACTIVITY,
                    summary=self.env._(
                        "Wallet sync failed for %(order)s", order=self.name
                    ),
                    note=message,
                    user_id=user.id,
                )
            return False
        if self.earlydryer_wallet_error:
            self.sudo().earlydryer_wallet_error = False
        return True

    def action_earlydryer_wallet_retry(self):
        for order in self:
            order._earlydryer_wallet_sync()
        return True

    def _earlydryer_wallet_payments(self):
        self.ensure_one()
        return self.payment_ids.filtered(
            lambda payment: (
                payment.payment_method_id.earlydryer_is_wallet
                and not payment.currency_id.is_zero(payment.amount)
            )
        )

    def _earlydryer_wallet_lines(self):
        self.ensure_one()
        return self.lines.filtered(
            lambda line: (
                line.product_id.earlydryer_kind == "wallet_topup"
                and not line.currency_id.is_zero(line.price_subtotal_incl)
            )
        )

    def _earlydryer_wallet_record(self):
        """One posted transaction per wallet payment and top-up line, without
        an entry of its own: the session closing carries the accounting.
        Idempotent (unique POS payment / line per transaction)."""
        self.ensure_one()
        order = self.sudo()
        Tx = self.env["earlydryer.wallet.transaction"].sudo()
        partner = order.partner_id.commercial_partner_id
        common = {
            "company": order.company_id,
            "source": "pos",
            "pos_order_id": order.id,
            "employee_id": order.employee_id.id,
            "user_id": order.user_id.id or self.env.uid,
            "earlydryer_branch_id": order.config_id.earlydryer_branch_id.id,
            "date": order.date_order,
            "laundry_job_id": order.earlydryer_job_id.id,
            "reference": order.pos_reference or order.name,
        }
        done_payments = Tx.search([("pos_payment_id", "in", order.payment_ids.ids)])
        done_lines = Tx.search([("pos_order_line_id", "in", order.lines.ids)])
        for line in order._earlydryer_wallet_lines() - done_lines.pos_order_line_id:
            amount = line.price_subtotal_incl
            if amount > 0:
                tx = Tx._earlydryer_new(
                    partner, "topup", amount, pos_order_line_id=line.id, **common
                )
            else:
                original = Tx.search(
                    [("pos_order_line_id", "=", line.refunded_orderline_id.id)],
                    limit=1,
                )
                tx = order._earlydryer_wallet_reverse_or_new(
                    partner,
                    original,
                    -amount,
                    "spend",
                    self.env._("Top-up refunded at the till"),
                    {"pos_order_line_id": line.id, **common},
                )
            tx._earlydryer_post(allow_overdraw=True)
        for payment in (
            order._earlydryer_wallet_payments() - done_payments.pos_payment_id
        ):
            amount = payment.amount
            if amount > 0:
                tx = Tx._earlydryer_new(
                    partner, "spend", amount, pos_payment_id=payment.id, **common
                )
            else:
                # refund paid back to the wallet: reverse the original spend
                refunded = order.lines.refunded_orderline_id.order_id
                original = Tx.search(
                    [
                        ("pos_order_id", "in", refunded.ids),
                        ("type", "=", "spend"),
                        ("reversal_id", "=", False),
                        ("amount", "=", -amount),
                    ],
                    limit=1,
                )
                tx = order._earlydryer_wallet_reverse_or_new(
                    partner,
                    original,
                    -amount,
                    "topup",
                    self.env._("Refunded to the wallet at the till"),
                    {"pos_payment_id": payment.id, **common},
                )
            tx._earlydryer_post(allow_overdraw=True)
        return True

    @api.model
    def _earlydryer_wallet_reverse_or_new(
        self, partner, original, amount, fallback_type, reason, vals
    ):
        """Reversal of ``original`` when it matches the refunded amount, else a
        plain transaction of ``fallback_type``."""
        Tx = self.env["earlydryer.wallet.transaction"].sudo()
        if original and not original.reversal_id and original.amount == amount:
            return Tx._earlydryer_new(
                partner,
                "reversal",
                amount,
                reversed_id=original.id,
                reason=reason,
                **vals,
            )
        return Tx._earlydryer_new(partner, fallback_type, amount, reason=reason, **vals)
