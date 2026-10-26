# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class PosPayment(models.Model):
    _inherit = "pos.payment"

    def _create_payment_moves(self, is_reverse=False):
        """Invoiced POS orders: core posts no move for journal-less (pay
        later) payments, so a wallet payment would leave the invoice open.
        While the session is open, post Dr Customer advances / Cr receivable
        and let core reconcile it with the invoice. After closing
        (``is_reverse``) the closing entry already debited the advances and
        core's reversal entry settles the invoice."""
        result = super()._create_payment_moves(is_reverse=is_reverse)
        if is_reverse:
            return result
        for payment in self.filtered(
            lambda payment: (
                payment.payment_method_id.earlydryer_is_wallet
                and not payment.currency_id.is_zero(payment.amount)
            )
        ):
            result |= payment._earlydryer_wallet_invoice_move()
        return result

    def _earlydryer_wallet_invoice_move(self):
        self.ensure_one()
        order = self.pos_order_id
        company = order.company_id
        partner = self.env["res.partner"]._find_accounting_partner(self.partner_id)
        session = order.session_id
        journal = session.config_id.journal_id
        amounts = session._update_amounts(
            {"amount": 0, "amount_converted": 0},
            {"amount": self.amount},
            self.payment_date,
        )
        move = (
            self.env["account.move"]
            .with_context(default_journal_id=journal.id)
            .create(
                {
                    "journal_id": journal.id,
                    "date": fields.Date.context_today(order, order.date_order),
                    "ref": self.env._(
                        "Wallet payment of %(order)s (%(invoice)s)",
                        order=order.name,
                        invoice=order.account_move.name,
                    ),
                    "pos_payment_ids": self.ids,
                }
            )
        )
        self.write({"account_move_id": move.id})
        MoveLine = self.env["account.move.line"]
        MoveLine.create(
            [
                session._credit_amounts(
                    {
                        "account_id": partner.with_company(
                            company
                        ).property_account_receivable_id.id,
                        "partner_id": partner.id,
                        "move_id": move.id,
                    },
                    amounts["amount"],
                    amounts["amount_converted"],
                ),
                session._debit_amounts(
                    {
                        "account_id": company.earlydryer_wallet_account_id.id,
                        "partner_id": partner.id,
                        "move_id": move.id,
                        "name": self.env._("Wallet payment"),
                    },
                    amounts["amount"],
                    amounts["amount_converted"],
                ),
            ]
        )
        move._post()
        return move
