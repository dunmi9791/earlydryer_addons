# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    # ------------------------------------------------------------------
    # Wallet payments: Dr Customer advances (customer), not the receivable
    # ------------------------------------------------------------------

    def _get_split_receivable_vals(self, payment, amount, amount_converted):
        vals = super()._get_split_receivable_vals(payment, amount, amount_converted)
        if payment.payment_method_id.earlydryer_is_wallet:
            vals["account_id"] = self.company_id.earlydryer_wallet_account_id.id
            vals["no_followup"] = True
        return vals

    def _create_pay_later_receivable_lines(self, data):
        data = super()._create_pay_later_receivable_lines(data)
        # core marks pay-later lines for follow-up; wallet lines are no debt
        lines = data.get("pay_later_move_lines")
        wallet_account = self.company_id.earlydryer_wallet_account_id
        if lines and wallet_account:
            lines.filtered(lambda line: line.account_id == wallet_account).write(
                {"no_followup": True}
            )
        return data

    def _get_receivable_account(self, payment_method):
        if payment_method.earlydryer_is_wallet:
            return self.company_id.earlydryer_wallet_account_id
        return super()._get_receivable_account(payment_method)

    # ------------------------------------------------------------------
    # Top-ups: Cr Customer advances per customer, not revenue
    # ------------------------------------------------------------------

    def _get_sale_key(self, base_line):
        key = super()._get_sale_key(base_line)
        line = base_line["record"]
        if (
            line._name == "pos.order.line"
            and line.product_id.earlydryer_kind == "wallet_topup"
        ):
            partner = line.order_id.partner_id.commercial_partner_id
            key["account_id"] = self.company_id.earlydryer_wallet_account_id.id
            key["earlydryer_wallet_partner_id"] = partner.id
        return key

    def _get_sale_vals(self, key, sale_vals):
        partner_id = key.get("earlydryer_wallet_partner_id")
        key = {k: v for k, v in key.items() if k != "earlydryer_wallet_partner_id"}
        vals = super()._get_sale_vals(key, sale_vals)
        if partner_id:
            vals.update(
                {
                    "name": self.env._("Wallet top-up"),
                    "partner_id": partner_id,
                    "tax_ids": [(6, 0, [])],
                    "tax_tag_ids": [(6, 0, [])],
                }
            )
        return vals

    # ------------------------------------------------------------------
    # Closing: wallet spends on POS jobs paid before the closing
    # ------------------------------------------------------------------

    def _validate_session(
        self,
        balancing_account=False,
        amount_to_balance=0,
        bank_payment_method_diffs=None,
    ):
        res = super()._validate_session(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs,
        )
        if self.state == "closed" and self.move_id.state == "posted":
            self.sudo()._earlydryer_reconcile_wallet_spends()
        return res

    def _earlydryer_reconcile_wallet_spends(self):
        """Backend wallet spends on this session's laundry jobs, made before
        the closing entry existed: reconcile their receivable credit now."""
        self.ensure_one()
        jobs = self.order_ids.earlydryer_job_id
        spends = jobs.earlydryer_wallet_transaction_ids.filtered(
            lambda tx: tx.type == "spend" and tx.state == "posted" and tx.move_id
        )
        for tx in spends:
            credit = tx._earlydryer_receivable_credit().filtered(
                lambda line: not line.reconciled
            )
            if not credit:
                continue
            debits = tx.laundry_job_id.pos_order_id._earlydryer_receivable_lines()
            debits = debits.filtered(
                lambda line, credit=credit: (
                    line.account_id == credit.account_id
                    and not line.reconciled
                    and line.balance > 0
                )
            )
            if debits:
                (credit | debits).reconcile()
