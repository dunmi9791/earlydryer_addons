# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

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
            # door payments of this session's jobs waited for the closing
            # entry (their pay-later receivable): match them now
            stops = self.env["earlydryer.logistics.stop"].sudo().search(
                [
                    ("job_id.pos_order_id", "in", self.order_ids.ids),
                    ("cod_payment_id", "!=", False),
                ]
            )
            stops._earlydryer_reconcile_cod_payment()
        return res
