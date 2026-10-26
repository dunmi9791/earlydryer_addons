# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class PosSession(models.Model):
    """Analytics of the session closing entry.

    Odoo 19 groups the sales of a session into one line per (account, sign,
    taxes, tags[, product]) in ``_get_sale_key`` and builds the line in
    ``_get_sale_vals``, without any analytic. The key gets the analytic
    distribution of the order line (plant of the till + service line of the
    product, or of the garment line for surcharge and express lines), so the
    revenue is split by service line and carries the plant.

    Every entry created while closing (session entry, cash statement lines,
    card payments, differences) gets the plant of the till, so their other
    lines take the plant analytic through the distribution models.
    """

    _inherit = "pos.session"

    def _earlydryer_line_distribution(self, line):
        branch = self.config_id.earlydryer_branch_id
        if not branch or line._name != "pos.order.line":
            return {}
        if line.product_id.earlydryer_kind in ("settlement", "wallet_topup"):
            return {}
        product = line.product_id.sudo()
        service_line = product.earlydryer_service_line_id
        if product.earlydryer_kind in ("surcharge", "express"):
            parent = line.earlydryer_parent_line_id
            if parent:
                service_line = parent.product_id.sudo().earlydryer_service_line_id
        distribution = {}
        plant = branch.sudo().analytic_account_id
        if plant:
            distribution[str(plant.id)] = 100.0
        if service_line:
            distribution[str(service_line.id)] = 100.0
        return distribution

    def _get_sale_key(self, base_line):
        key = super()._get_sale_key(base_line)
        distribution = self._earlydryer_line_distribution(base_line["record"])
        if distribution:
            key["earlydryer_analytic"] = tuple(sorted(distribution.items()))
        return key

    def _get_sale_vals(self, key, sale_vals):
        analytic = key.get("earlydryer_analytic")
        key = {k: v for k, v in key.items() if k != "earlydryer_analytic"}
        vals = super()._get_sale_vals(key, sale_vals)
        if analytic:
            vals["analytic_distribution"] = dict(analytic)
        return vals

    def _create_account_move(
        self,
        balancing_account=False,
        amount_to_balance=0,
        bank_payment_method_diffs=None,
    ):
        branch = self.config_id.earlydryer_branch_id
        session = self.with_context(earlydryer_move_branch_id=branch.id or False)
        return super(PosSession, session)._create_account_move(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs,
        )

    def _validate_session(
        self,
        balancing_account=False,
        amount_to_balance=0,
        bank_payment_method_diffs=None,
    ):
        branch = self.config_id.earlydryer_branch_id
        session = self.with_context(earlydryer_move_branch_id=branch.id or False)
        return super(PosSession, session)._validate_session(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs,
        )
