# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command

from .earlydryer_wallet import BRANCH_MANAGER, FINANCE, FRONT_DESK, WALLET_WRITE_CTX

_logger = logging.getLogger(__name__)

TYPES = [
    ("topup", "Top-up"),
    ("spend", "Spend"),
    ("refund", "Refund"),
    ("credit", "Credit"),
    ("migration", "Migration"),
    ("reversal", "Reversal"),
]
# sign of each type on the balance (a reversal takes the opposite of its original)
SIGNS = {"topup": 1, "credit": 1, "migration": 1, "spend": -1, "refund": -1}
SOURCES = [
    ("backend", "Backend"),
    ("pos", "Point of Sale"),
    ("gateway", "Payment Gateway"),
    ("claim", "Claim"),
    ("import", "Import"),
]
APPROVAL_TYPES = {"refund": "wallet_refund", "credit": "wallet_credit"}
TODO_ACTIVITY = "mail.mail_activity_data_todo"
# fields a posted transaction may still receive (links, flags, reversal)
POSTED_WRITABLE = {
    "reversal_id",
    "overdrawn",
    "shortfall",
    "message_main_attachment_id",
}


class EarlydryerWalletTransaction(models.Model):
    _name = "earlydryer.wallet.transaction"
    _description = "Earlydryer Wallet Transaction"
    _inherit = ["mail.thread", "mail.activity.mixin", "earlydryer.approval.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        required=True, readonly=True, copy=False, default=lambda self: self.env._("New")
    )
    wallet_id = fields.Many2one(
        "earlydryer.wallet",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    partner_id = fields.Many2one(
        related="wallet_id.partner_id", store=True, index=True, string="Customer"
    )
    partner_phone = fields.Char(related="partner_id.phone", string="Phone")
    company_id = fields.Many2one(
        related="wallet_id.company_id", store=True, index=True, string="Company"
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    type = fields.Selection(TYPES, required=True, readonly=True, index=True)
    amount = fields.Monetary(required=True, readonly=True)
    signed_amount = fields.Monetary(
        compute="_compute_signed_amount",
        store=True,
        recursive=True,
        string="Balance Effect",
    )
    date = fields.Datetime(
        required=True, readonly=True, default=fields.Datetime.now, index=True
    )
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Branch",
        readonly=True,
        index=True,
        help="Where it happened (reporting only: the wallet is usable at every plant).",
    )
    user_id = fields.Many2one(
        "res.users",
        readonly=True,
        default=lambda self: self.env.user,
        index=True,
    )
    employee_id = fields.Many2one("hr.employee", string="POS Employee", readonly=True)
    payment_journal_id = fields.Many2one("account.journal", readonly=True)
    move_id = fields.Many2one(
        "account.move", string="Journal Entry", readonly=True, copy=False, index=True
    )
    payment_id = fields.Many2one("account.payment", readonly=True, copy=False)
    invoice_id = fields.Many2one("account.move", readonly=True, index="btree_not_null")
    pos_order_id = fields.Many2one(
        "pos.order", string="POS Order", readonly=True, index="btree_not_null"
    )
    pos_payment_id = fields.Many2one(
        "pos.payment",
        string="POS Payment",
        readonly=True,
        index="btree_not_null",
        ondelete="set null",
    )
    pos_order_line_id = fields.Many2one(
        "pos.order.line",
        string="POS Order Line",
        readonly=True,
        index="btree_not_null",
        ondelete="set null",
    )
    pos_session_id = fields.Many2one(
        related="pos_order_id.session_id", string="POS Session"
    )
    laundry_job_id = fields.Many2one(
        "laundry.job", readonly=True, index="btree_not_null"
    )
    reversed_id = fields.Many2one(
        "earlydryer.wallet.transaction",
        string="Reverses",
        readonly=True,
        index="btree_not_null",
    )
    reversal_id = fields.Many2one(
        "earlydryer.wallet.transaction",
        string="Reversed By",
        readonly=True,
        copy=False,
    )
    reference = fields.Char(help="Bank transfer reference, claim number...")
    reason = fields.Text(readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")],
        required=True,
        default="draft",
        readonly=True,
        tracking=True,
        index=True,
    )
    source = fields.Selection(SOURCES, required=True, default="backend", readonly=True)
    import_ref = fields.Char(
        string="Import Reference",
        readonly=True,
        copy=False,
        help="Reference of the migrated balance (makes re-imports idempotent).",
    )
    overdrawn = fields.Boolean(
        readonly=True,
        copy=False,
        help="Spent at an offline till beyond the server balance: recorded, "
        "not refused, and Finance was told.",
    )
    shortfall = fields.Monetary(readonly=True, copy=False)
    approval_state = fields.Selection(
        [
            ("none", "Not Needed"),
            ("pending", "Waiting Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        compute="_compute_approval_state",
    )

    _import_ref_uniq = models.UniqueIndex(
        "(company_id, import_ref) WHERE import_ref IS NOT NULL",
        "This balance was already imported.",
    )
    _pos_payment_uniq = models.UniqueIndex(
        "(pos_payment_id) WHERE pos_payment_id IS NOT NULL",
        "A POS wallet payment is recorded once.",
    )
    _pos_line_uniq = models.UniqueIndex(
        "(pos_order_line_id) WHERE pos_order_line_id IS NOT NULL",
        "A POS top-up line is recorded once.",
    )
    _amount_positive = models.Constraint(
        "CHECK(amount > 0)", "The amount of a wallet transaction must be positive."
    )

    @api.depends("type", "amount", "reversed_id.signed_amount", "reversed_id.type")
    def _compute_signed_amount(self):
        for tx in self:
            if tx.type == "reversal":
                sign = -1 if tx.reversed_id.signed_amount > 0 else 1
            else:
                sign = SIGNS.get(tx.type, 0)
            tx.signed_amount = sign * tx.amount

    def _compute_approval_state(self):
        for tx in self:
            requests = tx.earlydryer_approval_request_ids.sorted("id")
            last = requests[-1:]
            if tx.type not in APPROVAL_TYPES or not last:
                tx.approval_state = "none"
            else:
                tx.approval_state = {
                    "pending": "pending",
                    "approved": "approved",
                    "rejected": "rejected",
                }.get(last.state, "none")

    @api.constrains("type", "reason", "reversed_id")
    def _check_reason(self):
        for tx in self:
            if (
                tx.type in ("refund", "credit", "reversal")
                and not (tx.reason or "").strip()
            ):
                raise ValidationError(
                    self.env._(
                        "A reason is required for refunds, credits and reversals."
                    )
                )
            if tx.type == "reversal" and not tx.reversed_id:
                raise ValidationError(
                    self.env._("A reversal must name the transaction it reverses.")
                )

    # ------------------------------------------------------------------
    # CRUD: through the model methods only
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.context.get(WALLET_WRITE_CTX):
            raise AccessError(
                self.env._("Wallet transactions are created by the wallet actions.")
            )
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code(
                    "earlydryer.wallet.transaction"
                ) or self.env._("New")
        return super().create(vals_list)

    def write(self, vals):
        internal = self.env.context.get(WALLET_WRITE_CTX)
        if not self.env.su and not internal:
            raise AccessError(
                self.env._("Wallet transactions change through their actions only.")
            )
        posted = any(tx.state != "draft" for tx in self)
        if not internal and posted and vals.keys() - POSTED_WRITABLE:
            raise UserError(
                self.env._("Posted wallet transactions are never edited: reverse them.")
            )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_never_posted(self):
        if any(tx.state == "posted" or tx.move_id for tx in self):
            raise UserError(
                self.env._(
                    "Posted wallet transactions are never deleted: reverse them."
                )
            )

    def _earlydryer_write(self, vals):
        return self.sudo().with_context(**{WALLET_WRITE_CTX: True}).write(vals)

    # ------------------------------------------------------------------
    # Creation (used by wizards, POS sync, migration, later modules)
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_new(self, partner, tx_type, amount, company=None, **vals):
        """Draft transaction on ``partner``'s wallet (created when missing)."""
        company = company or self.env.company
        company._earlydryer_wallet_check_setup()
        currency = company.currency_id
        amount = currency.round(amount or 0.0)
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise UserError(self.env._("The amount must be positive."))
        wallet = self.env["earlydryer.wallet"]._earlydryer_get(
            partner, company, create=True
        )
        vals.setdefault("user_id", self.env.uid)
        return (
            self.sudo()
            .with_context(**{WALLET_WRITE_CTX: True})
            .create(
                {
                    "wallet_id": wallet.id,
                    "type": tx_type,
                    "amount": amount,
                    **vals,
                }
            )
        )

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def action_post(self):
        """Post draft transactions after the right and approval checks."""
        Wallet = self.env["earlydryer.wallet"]
        for tx in self:
            if tx.type in ("topup", "spend"):
                Wallet._earlydryer_check_right(tx.type)
            elif tx.type in APPROVAL_TYPES:
                Wallet._earlydryer_check_right(tx.type)
                tx._earlydryer_approval_ensure(APPROVAL_TYPES[tx.type], tx.amount)
            elif tx.type == "migration":
                Wallet._earlydryer_check_right("import")
            elif tx.type == "reversal":
                Wallet._earlydryer_check_right("reverse")
            tx.sudo()._earlydryer_post()
        return True

    def _earlydryer_submit(self):
        """Refund and credit: post when no (more) approval is needed, else
        request it; the transaction stays draft until approved.

        :returns: True when posted
        """
        self.ensure_one()
        approval_type = APPROVAL_TYPES[self.type]
        self.env["earlydryer.wallet"]._earlydryer_check_right(self.type)
        if self._earlydryer_approval_check(approval_type, self.amount):
            self.sudo()._earlydryer_post()
            return True
        self.action_earlydryer_request_approval(approval_type, self.amount, self.reason)
        return False

    def _earlydryer_on_approval_decided(self, request):
        res = super()._earlydryer_on_approval_decided(request)
        tx = self.sudo()
        if tx.state != "draft" or request.approval_type != APPROVAL_TYPES.get(tx.type):
            return res
        if request.state == "approved":
            try:
                with self.env.cr.savepoint():
                    tx._earlydryer_post()
            except UserError as error:
                # e.g. the balance was spent meanwhile: keep the approval, say why
                tx.message_post(
                    body=self.env._(
                        "Approved but not posted: %(error)s", error=str(error)
                    ),
                    subtype_xmlid="mail.mt_note",
                )
        elif request.state == "rejected":
            tx._earlydryer_write({"state": "cancelled"})
        return res

    def _earlydryer_post(self, allow_overdraw=False):
        """Post one draft transaction: lock the wallet, check the balance,
        create the accounting entry (except POS transactions, whose
        accounting is the session closing entry) and call the hook.

        :param allow_overdraw: POS sale already made offline: record it and
            flag the shortfall instead of refusing
        """
        self.ensure_one()
        if self.state != "draft":
            raise UserError(self.env._("%(name)s is not a draft.", name=self.name))
        wallet = self.wallet_id
        wallet._earlydryer_lock()
        currency = self.currency_id
        if self.type in ("topup", "spend") and self.source != "pos":
            wallet._earlydryer_check_usable()
        if self.type == "reversal":
            original = self.reversed_id
            if original.state != "posted" or (
                original.reversal_id and original.reversal_id != self
            ):
                raise UserError(
                    self.env._(
                        "%(name)s is not posted or already reversed.",
                        name=original.name,
                    )
                )
        signed = self.signed_amount
        vals = {"state": "posted"}
        if currency.compare_amounts(signed, 0.0) < 0:
            balance = wallet._earlydryer_posted_balance()
            after = balance + signed
            if currency.compare_amounts(after, 0.0) < 0:
                if not allow_overdraw:
                    raise UserError(
                        self.env._(
                            "The wallet of %(partner)s holds %(balance)s, less than "
                            "%(amount)s.",
                            partner=wallet.partner_id.display_name,
                            balance=self._earlydryer_format(balance),
                            amount=self._earlydryer_format(-signed),
                        )
                    )
                vals.update(
                    overdrawn=True,
                    shortfall=currency.round(-after)
                    if currency.compare_amounts(balance, 0.0) >= 0
                    else -signed,
                )
        if self.source != "pos" and not self.move_id:
            vals.update(self._earlydryer_create_accounting())
        self._earlydryer_write(vals)
        if self.type == "reversal":
            self.reversed_id._earlydryer_write({"reversal_id": self.id})
        if self.overdrawn:
            self._earlydryer_notify_overdrawn()
        self._earlydryer_on_wallet_transaction_posted()
        return True

    def _earlydryer_on_wallet_transaction_posted(self):
        """Hook: called after a transaction is posted (notifications will send
        the customer the new balance)."""
        return

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------

    def _earlydryer_format(self, amount):
        currency = self.currency_id or self.env.company.currency_id
        return f"{currency.symbol or ''}{amount:,.2f}"

    def _earlydryer_label(self):
        self.ensure_one()
        type_label = dict(self._fields["type"]._description_selection(self.env))[
            self.type
        ]
        return self.env._(
            "Wallet %(type)s %(name)s", type=type_label.lower(), name=self.name
        )

    def _earlydryer_advances_line(self, debit=0.0, credit=0.0, partner=None):
        self.ensure_one()
        partner = partner or self.partner_id
        return Command.create(
            {
                "name": self._earlydryer_label(),
                "account_id": self.company_id.earlydryer_wallet_account_id.id,
                "partner_id": partner.id,
                "debit": debit,
                "credit": credit,
            }
        )

    def _earlydryer_prepare_move_vals(self):
        """Values of the journal entry of this transaction (see the accounting
        model in the README). Top-ups and refunds are account.payment records
        (see _earlydryer_prepare_payment_vals), reversals reverse the original
        entry; this builds the miscellaneous entries."""
        self.ensure_one()
        company = self.company_id
        partner = self.partner_id
        amount = self.amount
        if self.type == "spend":
            receivable = partner.with_company(company).property_account_receivable_id
            lines = [
                self._earlydryer_advances_line(debit=amount),
                Command.create(
                    {
                        "name": self._earlydryer_label(),
                        "account_id": receivable.id,
                        "partner_id": partner.id,
                        "credit": amount,
                    }
                ),
            ]
        elif self.type == "credit":
            account = company.earlydryer_wallet_credit_account_id
            if not account:
                raise UserError(
                    self.env._("Set the goodwill and claims account of the wallet.")
                )
            lines = [
                Command.create(
                    {
                        "name": self._earlydryer_label(),
                        "account_id": account.id,
                        "partner_id": partner.id,
                        "debit": amount,
                    }
                ),
                self._earlydryer_advances_line(credit=amount),
            ]
        elif self.type == "migration":
            lines = [
                Command.create(
                    {
                        "name": self._earlydryer_label(),
                        "account_id": self._earlydryer_opening_account().id,
                        "partner_id": partner.id,
                        "debit": amount,
                    }
                ),
                self._earlydryer_advances_line(credit=amount),
            ]
        else:
            raise UserError(
                self.env._(
                    "No journal entry is built for %(name)s this way.", name=self.name
                )
            )
        return {
            "move_type": "entry",
            "journal_id": company.earlydryer_wallet_journal_id.id,
            "company_id": company.id,
            "date": fields.Date.context_today(self, self.date),
            "ref": " ".join(filter(None, [self._earlydryer_label(), self.reference])),
            "line_ids": lines,
        }

    def _earlydryer_opening_account(self):
        company = self.company_id or self.env.company
        account = (
            company.earlydryer_wallet_opening_account_id
            or company.get_unaffected_earnings_account()
        )
        return account

    def _earlydryer_prepare_payment_vals(self):
        """account.payment of a top-up (inbound) or refund (outbound): the
        destination account is the customer advances instead of the
        receivable (Odoo 19 allows it: ``destination_account_id`` is stored
        and writable)."""
        self.ensure_one()
        journal = self.payment_journal_id
        if not journal:
            raise UserError(self.env._("Choose the payment journal."))
        payment_type = "inbound" if self.type == "topup" else "outbound"
        method_lines = (
            journal.inbound_payment_method_line_ids
            if payment_type == "inbound"
            else journal.outbound_payment_method_line_ids
        )
        vals = {}
        if journal.type == "cash" and journal.default_account_id:
            # cash: straight to the till's cash account (point_of_sale's
            # forced outstanding account); bank: Outstanding Receipts, matched
            # with the bank statement as usual
            vals["force_outstanding_account_id"] = journal.default_account_id.id
        return {
            **vals,
            "payment_type": payment_type,
            "partner_type": "customer",
            "partner_id": self.partner_id.id,
            "amount": self.amount,
            "currency_id": self.currency_id.id,
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "payment_method_line_id": method_lines[:1].id,
            "date": fields.Date.context_today(self, self.date),
            "memo": " ".join(filter(None, [self._earlydryer_label(), self.reference])),
            "destination_account_id": self.company_id.earlydryer_wallet_account_id.id,
        }

    def _earlydryer_create_accounting(self):
        """Create and post the entry; returns the transaction values to write."""
        self.ensure_one()
        if self.type in ("topup", "refund"):
            payment = (
                self.env["account.payment"]
                .sudo()
                .with_company(self.company_id)
                .create(self._earlydryer_prepare_payment_vals())
            )
            payment.action_post()
            if not payment.move_id:
                raise UserError(
                    self.env._(
                        "The payment of %(name)s has no journal entry.", name=self.name
                    )
                )
            if payment.move_id.state == "draft":
                payment.move_id.action_post()
            return {"payment_id": payment.id, "move_id": payment.move_id.id}
        if self.type == "reversal":
            return {"move_id": self._earlydryer_create_reversal_move().id}
        move = (
            self.env["account.move"]
            .sudo()
            .with_company(self.company_id)
            .create(self._earlydryer_prepare_move_vals())
        )
        move.action_post()
        if self.type == "spend":
            self._earlydryer_reconcile_spend(move)
        return {"move_id": move.id}

    def _earlydryer_receivable_credit(self, move=None):
        """The receivable credit line of a spend entry."""
        self.ensure_one()
        move = move or self.move_id
        return move.line_ids.filtered(
            lambda line: (
                line.account_id.account_type == "asset_receivable"
                and line.partner_id == self.partner_id
                and line.credit > 0
            )
        )

    def _earlydryer_reconcile_spend(self, move):
        """Reconcile the receivable credit of a spend with what it pays: the
        invoice, or the open POS receivable of the laundry job."""
        self.ensure_one()
        credit = self._earlydryer_receivable_credit(move)
        if self.invoice_id:
            debits = self.invoice_id.line_ids.filtered(
                lambda line: (
                    line.account_id == credit.account_id
                    and not line.reconciled
                    and line.balance > 0
                )
            )
        elif self.laundry_job_id.pos_order_id:
            debits = self.laundry_job_id.pos_order_id._earlydryer_receivable_lines()
            debits = debits.filtered(
                lambda line: (
                    line.account_id == credit.account_id
                    and not line.reconciled
                    and line.balance > 0
                )
            )
        else:
            debits = self.env["account.move.line"]
        if debits:
            (credit | debits).reconcile()
        return True

    def _earlydryer_create_reversal_move(self):
        """Entry of a reversal: the reversal move of the original entry (a
        migration shares one summary entry: mirror this customer's part)."""
        self.ensure_one()
        original = self.reversed_id
        move = original.move_id
        if not move:
            raise UserError(
                self.env._(
                    "%(name)s has no journal entry of its own (till transaction): "
                    "correct it at the till with a refund.",
                    name=original.name,
                )
            )
        date = fields.Date.context_today(self, self.date)
        ref = self.env._(
            "Reversal of %(name)s: %(reason)s", name=original.name, reason=self.reason
        )
        if original.type == "migration":
            vals = original._earlydryer_prepare_move_vals()
            for _cmd, _id, line in vals["line_ids"]:
                line["debit"], line["credit"] = line["credit"], line["debit"]
            vals.update(date=date, ref=ref)
            reversal = self.env["account.move"].sudo().create(vals)
            reversal.action_post()
            return reversal
        # spends: give the invoice its residual back before reversing
        if original.type == "spend":
            move.line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_receivable"
            ).remove_move_reconcile()
        # cancel=True posts the reversal and reconciles it with the original
        return move.sudo()._reverse_moves([{"date": date, "ref": ref}], cancel=True)

    # ------------------------------------------------------------------
    # Reversal
    # ------------------------------------------------------------------

    def _earlydryer_reverse(self, reason, date=None):
        """Create and post the reversal of this posted transaction."""
        self.ensure_one()
        self.env["earlydryer.wallet"]._earlydryer_check_right("reverse")
        if not (reason or "").strip():
            raise UserError(self.env._("Give the reason of the reversal."))
        if self.state != "posted" or self.reversal_id or self.type == "reversal":
            raise UserError(
                self.env._(
                    "%(name)s cannot be reversed (not posted, already reversed or "
                    "a reversal itself).",
                    name=self.name,
                )
            )
        if not self.move_id:
            raise UserError(
                self.env._(
                    "%(name)s has no journal entry of its own (till transaction): "
                    "correct it at the till with a refund.",
                    name=self.name,
                )
            )
        reversal = self._earlydryer_new(
            self.partner_id,
            "reversal",
            self.amount,
            company=self.company_id,
            reversed_id=self.id,
            reason=reason,
            date=date or fields.Datetime.now(),
            earlydryer_branch_id=self.earlydryer_branch_id.id,
            invoice_id=self.invoice_id.id,
            laundry_job_id=self.laundry_job_id.id,
            payment_journal_id=self.payment_journal_id.id,
            source="backend",
        )
        reversal._earlydryer_post()
        return reversal

    def action_open_reverse_wizard(self):
        self.ensure_one()
        self.env["earlydryer.wallet"]._earlydryer_check_right("reverse")
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Reverse Wallet Transaction"),
            "res_model": "earlydryer.wallet.reverse.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_transaction_id": self.id},
        }

    def action_submit(self):
        """Button of a draft refund or credit: post, or ask approval."""
        for tx in self:
            tx._earlydryer_submit()
        return True

    def action_cancel(self):
        for tx in self:
            if tx.state != "draft":
                raise UserError(self.env._("Only draft transactions can be cancelled."))
            if tx.user_id != self.env.user:
                self.env["earlydryer.wallet"]._earlydryer_check_right("reverse")
            pending = tx.earlydryer_approval_request_ids.filtered(
                lambda request: request.state == "pending"
            )
            if pending:
                pending.sudo().action_cancel()
            tx._earlydryer_write({"state": "cancelled"})
        return True

    def action_open_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
        }

    # ------------------------------------------------------------------
    # Overdraw (offline tills)
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_finance_users(self, company=None):
        company = company or self.company_id[:1] or self.env.company
        group = self.env.ref(FINANCE).sudo()
        return group.all_user_ids.filtered(
            lambda user: (
                user.active
                and not user.share
                and company in user.company_ids
                and not user._is_superuser()
            )
        )

    def _earlydryer_notify_overdrawn(self):
        """Offline overdraw: activity for Finance, branch manager told."""
        self.ensure_one()
        tx = self.sudo()
        message = self.env._(
            "%(name)s spent %(amount)s at an offline till; the wallet of "
            "%(partner)s is short by %(shortfall)s. The sale stands: recover the "
            "difference from the customer.",
            name=tx.name,
            amount=tx._earlydryer_format(tx.amount),
            partner=tx.partner_id.display_name,
            shortfall=tx._earlydryer_format(tx.shortfall),
        )
        tx.message_post(body=message, subtype_xmlid="mail.mt_note")
        tx.wallet_id.message_post(body=message, subtype_xmlid="mail.mt_note")
        users = tx._earlydryer_finance_users(tx.company_id)
        config = tx.pos_order_id.config_id
        if config:
            users |= config._earlydryer_manager_users()
        elif tx.earlydryer_branch_id.manager_id:
            users |= tx.earlydryer_branch_id.manager_id
        summary = self.env._(
            "Wallet overdrawn: %(partner)s", partner=tx.partner_id.name
        )
        for user in users:
            tx.activity_schedule(
                TODO_ACTIVITY, summary=summary, note=message, user_id=user.id
            )
        return True

    # ------------------------------------------------------------------
    # Top-up rights
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_check_topup_journal(self, journal):
        """Front Desk tops up in cash on their own plant's cash journal only;
        Branch Managers and Finance use any cash, bank or card journal."""
        Wallet = self.env["earlydryer.wallet"]
        Wallet._earlydryer_check_right("topup")
        if journal.type not in ("cash", "bank"):
            raise UserError(self.env._("Top-ups are paid into a cash or bank journal."))
        user = self.env.user
        if self.env.su or user.has_group(BRANCH_MANAGER) or user.has_group(FINANCE):
            return True
        if user.has_group(FRONT_DESK):
            own = user._earlydryer_allowed_branches().cash_journal_id
            if journal not in own:
                raise AccessError(
                    self.env._(
                        "Front Desk tops up in cash on the cash journal of their "
                        "own plant."
                    )
                )
        return True
