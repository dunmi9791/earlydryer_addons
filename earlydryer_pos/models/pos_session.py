# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# loaded after the products, so surcharge products resolve
EARLYDRYER_POS_MODELS = [
    "earlydryer.garment.category",
    "earlydryer.service.type",
    "earlydryer.surcharge",
    "earlydryer.approval.rule",
]


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        data = super()._load_pos_data_models(config)
        if config.earlydryer_enabled:
            data += [model for model in EARLYDRYER_POS_MODELS if model not in data]
        return data

    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        try:
            with self.env.cr.savepoint():
                sessions.config_id._earlydryer_top_up_tag_ranges()
        except Exception:  # pylint: disable=broad-except  # never block the till
            _logger.exception("Earlydryer tag range top-up failed on session open.")
        return sessions

    # ------------------------------------------------------------------
    # Balance settlements: receivable, not revenue
    # ------------------------------------------------------------------

    def _get_sale_key(self, base_line):
        key = super()._get_sale_key(base_line)
        line = base_line["record"]
        if (
            line._name == "pos.order.line"
            and line.product_id.earlydryer_kind == "settlement"
        ):
            partner = line.order_id.partner_id.commercial_partner_id
            key["account_id"] = partner.property_account_receivable_id.id
            key["earlydryer_settlement_partner_id"] = partner.id
        return key

    def _get_sale_vals(self, key, sale_vals):
        partner_id = key.get("earlydryer_settlement_partner_id")
        key = {k: v for k, v in key.items() if k != "earlydryer_settlement_partner_id"}
        vals = super()._get_sale_vals(key, sale_vals)
        if partner_id:
            vals.update(
                {
                    "name": self.env._("Balance settlement"),
                    "partner_id": partner_id,
                    "display_type": "payment_term",
                    "tax_ids": [(6, 0, [])],
                    "tax_tag_ids": [(6, 0, [])],
                    "product_id": False,
                    "product_uom_id": False,
                    "earlydryer_settlement": True,
                }
            )
        return vals

    def _earlydryer_settlement_lines(self):
        """Session move lines of the balance settlements (receivable credits)."""
        self.ensure_one()
        return self.move_id.line_ids.filtered(
            lambda line: line.earlydryer_settlement
            and not line.reconciled
            and line.account_id.reconcile
        )

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
            self.sudo()._earlydryer_reconcile_settlements()
        return res

    def _earlydryer_reconcile_settlements(self):
        """Reconcile each settlement credit with the open receivable of the
        jobs it pays (pay-later receivable of their POS order, or its invoice),
        then with any other open receivable of the customer, oldest first."""
        self.ensure_one()
        AccountMoveLine = self.env["account.move.line"]
        for credit in self._earlydryer_settlement_lines():
            partner = credit.partner_id
            orders = self.order_ids.filtered(
                lambda order, partner=partner: order.partner_id.commercial_partner_id
                == partner
                and order.earlydryer_settlement_job_ids
            )
            jobs = orders.earlydryer_settlement_job_ids
            candidates = jobs.pos_order_id._earlydryer_receivable_lines()
            others = AccountMoveLine.search(
                [
                    ("partner_id", "=", partner.id),
                    ("account_id", "=", credit.account_id.id),
                    ("reconciled", "=", False),
                    ("parent_state", "=", "posted"),
                    ("balance", ">", 0),
                    ("id", "not in", candidates.ids),
                ],
                order="date, id",
            )
            debits = candidates.sorted(lambda line: (line.date, line.id)) | others
            debits = debits.filtered(
                lambda line, credit=credit: line.account_id == credit.account_id
                and not line.reconciled
            )
            if debits:
                (credit | debits).reconcile()
