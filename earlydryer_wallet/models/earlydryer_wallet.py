# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tools import SQL

# who may do what (enforced in Python, see _earlydryer_check_right); a group
# implies the groups below it (Branch Manager > Front Desk and Customer
# Service, Management > Finance and Branch Manager, Administrator > all)
FRONT_DESK = "earlydryer_base.group_front_desk"
CUSTOMER_SERVICE = "earlydryer_base.group_customer_service"
BRANCH_MANAGER = "earlydryer_base.group_branch_manager"
FINANCE = "earlydryer_base.group_finance"
RIGHTS = {
    "topup": (FRONT_DESK, FINANCE),
    "spend": (FRONT_DESK, FINANCE),
    "refund": (FRONT_DESK, CUSTOMER_SERVICE, FINANCE),
    "credit": (CUSTOMER_SERVICE, FINANCE),
    "reverse": (FINANCE,),
    "import": (FINANCE,),
    "control": (FINANCE,),
    "block": (FINANCE,),
}
# internal context key: wallet rows are written by the model methods only
WALLET_WRITE_CTX = "earlydryer_wallet_write"


class EarlydryerWallet(models.Model):
    _name = "earlydryer.wallet"
    _description = "Earlydryer Customer Wallet"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "partner_id"
    _rec_name = "partner_id"

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    balance = fields.Monetary(
        compute="_compute_balance",
        store=True,
        help="Sum of the posted transactions. The wallet ledger is the "
        "subledger of record; see the control report.",
    )
    state = fields.Selection(
        [("active", "Active"), ("blocked", "Blocked")],
        required=True,
        default="active",
        readonly=True,
        tracking=True,
        help="A blocked wallet cannot be spent or topped up; Finance can still "
        "refund it.",
    )
    overdrawn = fields.Boolean(
        compute="_compute_balance",
        store=True,
        help="Negative balance: spent offline at two tills at once.",
    )
    transaction_ids = fields.One2many(
        "earlydryer.wallet.transaction", "wallet_id", string="Transactions"
    )
    last_transaction_date = fields.Datetime(compute="_compute_balance", store=True)
    last_topup_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Branch of Last Top-up",
        compute="_compute_balance",
        store=True,
    )
    partner_phone = fields.Char(related="partner_id.phone", string="Phone")
    transaction_count = fields.Integer(compute="_compute_transaction_count")

    _partner_company_uniq = models.Constraint(
        "unique(partner_id, company_id)",
        "A customer has one wallet per company.",
    )

    @api.depends(
        "transaction_ids.state",
        "transaction_ids.signed_amount",
        "transaction_ids.date",
    )
    def _compute_balance(self):
        for wallet in self:
            posted = wallet.transaction_ids.filtered(lambda tx: tx.state == "posted")
            balance = sum(posted.mapped("signed_amount"))
            wallet.balance = balance
            wallet.overdrawn = wallet.currency_id.compare_amounts(balance, 0.0) < 0
            wallet.last_transaction_date = max(posted.mapped("date"), default=False)
            topups = posted.filtered(lambda tx: tx.type == "topup").sorted(
                lambda tx: (tx.date, tx.id)
            )
            wallet.last_topup_branch_id = topups[-1:].earlydryer_branch_id

    def _compute_transaction_count(self):
        counts = dict(
            self.env["earlydryer.wallet.transaction"]._read_group(
                [("wallet_id", "in", self.ids)], ["wallet_id"], ["__count"]
            )
        )
        for wallet in self:
            wallet.transaction_count = counts.get(wallet, 0)

    # ------------------------------------------------------------------
    # CRUD: through the model methods only
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.context.get(WALLET_WRITE_CTX):
            raise AccessError(
                self.env._("Wallets are created by their first transaction.")
            )
        return super().create(vals_list)

    def write(self, vals):
        protected = vals.keys() - {"message_main_attachment_id"}
        if protected and not self.env.su and not self.env.context.get(WALLET_WRITE_CTX):
            raise AccessError(
                self.env._("Wallets change through their transactions only.")
            )
        return super().write(vals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_check_right(self, right, raise_error=True):
        """The current user may ``right`` (see RIGHTS); superuser always."""
        if self.env.su:
            return True
        user = self.env.user
        allowed = any(user.has_group(group) for group in RIGHTS[right])
        if not allowed and raise_error:
            labels = {
                "topup": self.env._("top up a wallet"),
                "spend": self.env._("pay from a wallet"),
                "refund": self.env._("request a wallet refund"),
                "credit": self.env._("request a wallet credit"),
                "reverse": self.env._("reverse a wallet transaction"),
                "import": self.env._("import wallet balances"),
                "control": self.env._("run the wallet control report"),
                "block": self.env._("block or unblock a wallet"),
            }
            raise AccessError(
                self.env._("You are not allowed to %(action)s.", action=labels[right])
            )
        return allowed

    @api.model
    def _earlydryer_get(self, partner, company=None, create=False):
        """Wallet of ``partner``'s commercial entity in ``company``."""
        company = company or self.env.company
        partner = partner.commercial_partner_id
        wallet = self.sudo().search(
            [("partner_id", "=", partner.id), ("company_id", "=", company.id)],
            limit=1,
        )
        if not wallet and create:
            wallet = (
                self.sudo()
                .with_context(**{WALLET_WRITE_CTX: True})
                .create({"partner_id": partner.id, "company_id": company.id})
            )
        return self.browse(wallet.id)

    def _earlydryer_lock(self):
        """Row lock of the wallets until the end of the transaction: two
        tills or users posting on one wallet run one after the other."""
        if self.ids:
            self.env.cr.execute(
                SQL(
                    "SELECT id FROM %s WHERE id IN %s FOR NO KEY UPDATE",
                    SQL.identifier(self._table),
                    tuple(self.ids),
                )
            )
        return True

    def _earlydryer_posted_balance(self):
        """Balance read from the database (after the lock), not the cache."""
        self.ensure_one()
        self.env["earlydryer.wallet.transaction"].flush_model(
            ["wallet_id", "state", "signed_amount"]
        )
        self.env.cr.execute(
            SQL(
                "SELECT COALESCE(SUM(signed_amount), 0) FROM %s "
                "WHERE wallet_id = %s AND state = 'posted'",
                SQL.identifier("earlydryer_wallet_transaction"),
                self.id,
            )
        )
        return self.env.cr.fetchone()[0]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_block(self):
        self._earlydryer_check_right("block")
        self.sudo().with_context(**{WALLET_WRITE_CTX: True}).state = "blocked"
        return True

    def action_unblock(self):
        self._earlydryer_check_right("block")
        self.sudo().with_context(**{WALLET_WRITE_CTX: True}).state = "active"
        return True

    def action_view_transactions(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_wallet.earlydryer_wallet_transaction_action"
        )
        action["domain"] = [("wallet_id", "=", self.id)]
        action["context"] = {"search_default_posted": 1}
        return action

    def _earlydryer_partner_action(self, xmlid):
        self.ensure_one()
        return self.partner_id._earlydryer_wallet_wizard(xmlid)

    def action_open_topup(self):
        return self._earlydryer_partner_action(
            "earlydryer_wallet.earlydryer_wallet_topup_wizard_action"
        )

    def action_open_refund(self):
        return self._earlydryer_partner_action(
            "earlydryer_wallet.earlydryer_wallet_refund_wizard_action"
        )

    def action_open_credit(self):
        return self._earlydryer_partner_action(
            "earlydryer_wallet.earlydryer_wallet_credit_wizard_action"
        )

    def action_open_statement(self):
        return self._earlydryer_partner_action(
            "earlydryer_wallet.earlydryer_wallet_statement_wizard_action"
        )

    # ------------------------------------------------------------------
    # POS
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_pos_balances(self, company):
        """``{partner_id: balance}`` of the wallets with a non-zero balance,
        loaded with the till (kept small)."""
        wallets = self.sudo().search(
            [("company_id", "=", company.id), ("balance", "!=", 0)]
        )
        return {
            str(wallet.partner_id.id): {
                "balance": wallet.balance,
                "blocked": wallet.state == "blocked",
            }
            for wallet in wallets
        }

    @api.model
    def get_balance(self, partner_id, order_uuids=None):
        """RPC of the till: the current balance of one customer, and which of
        the till's local wallet orders the server already counts."""
        self.check_access("read")
        partner = self.env["res.partner"].browse(int(partner_id)).exists()
        if not partner:
            return {"partner_id": partner_id, "balance": 0.0, "blocked": False}
        wallet = self._earlydryer_get(partner)
        synced = []
        if order_uuids:
            synced = (
                self.env["pos.order"]
                .sudo()
                .search([("uuid", "in", list(order_uuids))])
                .mapped("uuid")
            )
        return {
            "partner_id": partner.id,
            "balance": wallet.sudo().balance if wallet else 0.0,
            "blocked": bool(wallet) and wallet.sudo().state == "blocked",
            "synced_uuids": synced,
            "as_at": fields.Datetime.to_string(fields.Datetime.now()),
        }

    def _earlydryer_check_usable(self, raise_error=True):
        """Active wallet (blocked wallets are neither spent nor topped up)."""
        self.ensure_one()
        if self.state == "blocked":
            if raise_error:
                raise UserError(
                    self.env._(
                        "The wallet of %(partner)s is blocked.",
                        partner=self.partner_id.display_name,
                    )
                )
            return False
        return True

    # ------------------------------------------------------------------
    # Demo data
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_load_demo(self):
        """Demo only: settings, wallet method on the demo tills, top-ups,
        a spend on an invoice, a till wallet payment, a credit and a
        migration of three rows."""
        ref = self.env.ref
        # as the administrator: OdooBot has no Point of Sale rights
        env = self.with_user(ref("base.user_admin")).env
        company = env.company
        company.sudo()._earlydryer_wallet_setup()
        tills = ref("earlydryer_service_catalog.pos_config_counter_p1") | ref(
            "earlydryer_pos.pos_config_counter_p2"
        )
        tills.with_env(env).action_earlydryer_add_wallet_payment()
        Tx = env["earlydryer.wallet.transaction"]
        cash = ref("earlydryer_base.journal_cash_plant_1")
        transfer = ref("earlydryer_pos.journal_transfer")
        plant_1 = ref("earlydryer_base.branch_plant_1")
        plant_2 = ref("earlydryer_base.branch_plant_2")
        topups = [
            ("chioma", 20000, cash, plant_1, False),
            ("tunde", 15000, cash, plant_1, False),
            ("halima", 30000, transfer, plant_2, "TRF-0001"),
            ("emeka", 10000, cash, plant_1, False),
            ("grace", 25000, transfer, plant_2, "TRF-0002"),
        ]
        for name, amount, journal, branch, reference in topups:
            tx = Tx._earlydryer_new(
                ref(f"earlydryer_wallet.partner_wallet_{name}"),
                "topup",
                amount,
                company=company,
                payment_journal_id=journal.id,
                earlydryer_branch_id=branch.id,
                reference=reference,
            )
            tx.action_post()
        # a spend on a customer invoice
        chioma = ref("earlydryer_wallet.partner_wallet_chioma")
        product = env["product.product"].search(
            [("earlydryer_kind", "=", "laundry"), ("sale_ok", "=", True)], limit=1
        )
        invoice = env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": chioma.id,
                "invoice_line_ids": [
                    Command.create(
                        {"product_id": product.id, "quantity": 2, "price_unit": 4500}
                    )
                ],
            }
        )
        invoice.action_post()
        invoice._earlydryer_wallet_spend(min(invoice.amount_residual, 9000))
        # an approved goodwill credit (self-approved by a Branch Manager)
        credit = Tx._earlydryer_new(
            ref("earlydryer_wallet.partner_wallet_tunde"),
            "credit",
            2500,
            company=company,
            reason="Demo: shirt returned with a stain, goodwill credit.",
            earlydryer_branch_id=plant_1.id,
        )
        credit._earlydryer_submit()
        # a wallet payment at the Plant 1 till, session closed
        self._earlydryer_load_demo_pos(
            env, ref("earlydryer_wallet.partner_wallet_emeka")
        )
        # migration of three old notebook balances
        csv = (
            "ref,name,phone,balance,branch_code,note\n"
            "NB-001,Ngozi Okafor,08031110010,7500,,notebook page 3\n"
            "NB-002,Tunde Bakare,0803 111 0002,4000,,notebook page 7\n"
            "NB-003,Bello Yusuf,08031110012,12000,,notebook page 9\n"
        )
        wizard = env["earlydryer.wallet.import.wizard"].create(
            {
                "file": base64.b64encode(csv.encode()),
                "filename": "notebook_balances.csv",
                "as_of_date": fields.Date.context_today(self),
            }
        )
        wizard.action_import()
        return True

    @api.model
    def _earlydryer_load_demo_pos(self, env, partner):
        ref = self.env.ref
        config = ref("earlydryer_service_catalog.pos_config_counter_p1").with_env(env)
        if not config.current_session_id:
            config.open_ui()
        session = config.current_session_id
        wallet_method = config.payment_method_ids.filtered("earlydryer_is_wallet")
        cash = config.payment_method_ids.filtered("is_cash_count")[:1]
        product = env["product.product"].search(
            [("earlydryer_kind", "=", "retail"), ("available_in_pos", "=", True)],
            limit=1,
        ) or ref("earlydryer_wallet.product_wallet_topup")
        price = 3000.0
        topup = ref("earlydryer_wallet.product_wallet_topup")
        lines = [config._earlydryer_ui_line(product, 1, price, "ed-wallet-demo-1")]
        payments = [
            (0, 0, {"amount": 2000.0, "payment_method_id": wallet_method.id}),
            (0, 0, {"amount": 1000.0, "payment_method_id": cash.id}),
        ]
        orders = [
            {
                "uuid": f"ed-wallet-demo-order-{config.id}-1",
                "partner_id": partner.id,
                "lines": lines,
                "payment_ids": payments,
                "amount": price,
            },
            {
                "uuid": f"ed-wallet-demo-order-{config.id}-2",
                "partner_id": ref("earlydryer_wallet.partner_wallet_grace").id,
                "lines": [
                    config._earlydryer_ui_line(topup, 1, 5000.0, "ed-wallet-demo-2")
                ],
                "payment_ids": [
                    (0, 0, {"amount": 5000.0, "payment_method_id": cash.id})
                ],
                "amount": 5000.0,
            },
        ]
        payloads = []
        for number, order in enumerate(orders, start=1):
            payloads.append(
                {
                    "uuid": order["uuid"],
                    "name": f"Wallet demo {number}",
                    "session_id": session.id,
                    "partner_id": order["partner_id"],
                    "employee_id": ref(
                        "earlydryer_laundry_order.employee_front_desk_p1"
                    ).id,
                    "pricelist_id": config.pricelist_id.id,
                    "user_id": env.uid,
                    "lines": order["lines"],
                    "payment_ids": order["payment_ids"],
                    "amount_paid": order["amount"],
                    "amount_total": order["amount"],
                    "amount_tax": 0.0,
                    "amount_return": 0.0,
                    "date_order": fields.Datetime.to_string(fields.Datetime.now()),
                    "state": "paid",
                    "to_invoice": False,
                    "last_order_preparation_change": "{}",
                }
            )
        env["pos.order"].sync_from_ui(payloads)
        cash_total = sum(
            session.order_ids.payment_ids.filtered(
                lambda payment: payment.payment_method_id.is_cash_count
            ).mapped("amount")
        )
        session.post_closing_cash_details(cash_total)
        session.close_session_from_ui()
        return True
