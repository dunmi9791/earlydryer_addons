# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.fields import Command

from odoo.addons.earlydryer_pos.tests.common import EarlydryerPosCommon


class WalletCommon(EarlydryerPosCommon):
    """Wallet accounts and journal, the Wallet method on the test counters,
    and one user per role."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company._earlydryer_wallet_setup()
        cls.Wallet = cls.env["earlydryer.wallet"]
        cls.Tx = cls.env["earlydryer.wallet.transaction"]
        cls.advances = cls.company.earlydryer_wallet_account_id
        cls.branch_1.cash_journal_id = cls.journal_cash
        (cls.config | cls.config_2).action_earlydryer_add_wallet_payment()
        cls.pm_wallet = cls.config.payment_method_ids.filtered("earlydryer_is_wallet")
        cls.topup_product = cls.env.ref("earlydryer_wallet.product_wallet_topup")
        cls.bank = cls.env["account.journal"].create(
            {"name": "T Bank", "type": "bank", "code": "TBNK"}
        )
        cls.user_cs = cls._new_user(
            "t_customer_service", "earlydryer_base.group_customer_service", cls.branch_1
        )
        cls.user_management = cls._new_user(
            "t_management", "earlydryer_base.group_management"
        )
        cls.user_management_2 = cls._new_user(
            "t_management_2", "earlydryer_base.group_management"
        )
        cls.customer = cls.env["res.partner"].create(
            {"name": "T Wallet Customer", "phone": "+2348030000001"}
        )

    def setUp(self):
        super().setUp()
        # the database may hold demo wallets: tests compare with these
        self.gl_start = self._gl_advances()
        self.wallets_start = self._control().wallet_total

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _control(self, user=None):
        env = self.env(user=user) if user else self.env
        return env["earlydryer.wallet.control"].create({})

    def _sync(self, payload, env=None):
        """The synced order itself (the result may list the refunded one too)."""
        env = env or self.env
        env["pos.order"].sync_from_ui([payload])
        return env["pos.order"].search([("uuid", "=", payload["uuid"])], limit=1)

    def _topup(self, amount, partner=None, journal=None, user=None):
        env = self.env(user=user) if user else self.env
        wizard = env["earlydryer.wallet.topup.wizard"].create(
            {
                "partner_id": (partner or self.customer).id,
                "amount": amount,
                "journal_id": (journal or self.journal_cash).id,
                "earlydryer_branch_id": self.branch_1.id,
            }
        )
        wizard.action_confirm()
        return self.Tx.search(
            [
                ("partner_id", "=", (partner or self.customer).id),
                ("type", "=", "topup"),
            ],
            order="id desc",
            limit=1,
        )

    def _wallet(self, partner=None):
        wallet = self.Wallet._earlydryer_get(partner or self.customer)
        wallet.invalidate_recordset()
        return wallet

    def _balance(self, partner=None):
        return self._wallet(partner).balance

    def _invoice(self, amount, partner=None):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": (partner or self.customer).id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.shirt_wi.id,
                            "quantity": 1,
                            "price_unit": amount,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        invoice.action_post()
        return invoice

    def _gl_delta(self):
        return self._gl_advances() - self.gl_start

    def _gl_advances(self):
        """Credit balance of Customer Advances."""
        lines = self.env["account.move.line"].search(
            [("account_id", "=", self.advances.id), ("parent_state", "=", "posted")]
        )
        return -sum(lines.mapped("balance"))

    def _wallet_payload(self, lines, partner=None, wallet=0.0, cash=None, **extra):
        """A synced order paid ``wallet`` from the wallet, the rest in cash."""
        payload = self._payload(lines, partner=partner or self.customer, **extra)
        total = payload["amount_total"]
        cash_method = self.config.payment_method_ids.filtered("is_cash_count")[:1]
        cash = total - wallet if cash is None else cash
        payments = []
        if cash:
            payments.append(
                (0, 0, {"amount": cash, "payment_method_id": cash_method.id})
            )
        if wallet:
            payments.append(
                (0, 0, {"amount": wallet, "payment_method_id": self.pm_wallet.id})
            )
        payload["payment_ids"] = payments
        return payload
