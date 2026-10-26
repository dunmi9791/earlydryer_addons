# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

_logger = logging.getLogger(__name__)

CASH_KINDS = [
    ("lodgement", "Cash Lodgement"),
    ("rider_handover", "Rider Cash Handover"),
    ("opening_balance", "Opening Balances"),
    ("wht_deduction", "WHT Deducted by Customer"),
    ("wht_remittance", "WHT Remittance"),
]


class AccountMove(models.Model):
    _inherit = "account.move"

    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        index="btree_not_null",
        check_company=True,
        tracking=True,
        ondelete="restrict",
        compute="_compute_earlydryer_branch_id",
        store=True,
        readonly=False,
        precompute=True,
        help="Plant of the document: from the sales order, the POS session or "
        "the user's default plant. Drives the plant analytic.",
    )
    earlydryer_kind = fields.Selection(
        CASH_KINDS, string="Earlydryer Entry", readonly=True, copy=False, index=True
    )
    earlydryer_lodgement_journal_id = fields.Many2one(
        "account.journal",
        string="Lodged to Bank",
        readonly=True,
        copy=False,
        help="Bank journal the lodged cash goes to (reconciled from its statement).",
    )
    earlydryer_rider_employee_id = fields.Many2one(
        "hr.employee", string="Rider", readonly=True, copy=False
    )
    # WHT deducted by a customer from this invoice (on the deduction entry)
    earlydryer_wht_invoice_id = fields.Many2one(
        "account.move",
        string="WHT on Invoice",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
    earlydryer_wht_reference = fields.Char(
        string="Credit Note / Certificate Ref.",
        copy=False,
        tracking=True,
        help="Reference of the customer's WHT credit note or certificate.",
    )
    earlydryer_wht_certificate_date = fields.Date(
        string="Certificate Received On",
        copy=False,
        tracking=True,
        help="Empty while the WHT certificate is awaited.",
    )
    earlydryer_wht_deduction_ids = fields.One2many(
        "account.move", "earlydryer_wht_invoice_id", string="WHT Deductions"
    )
    earlydryer_wht_deducted = fields.Monetary(
        string="WHT Deducted by Customer",
        compute="_compute_earlydryer_wht_deducted",
        currency_field="company_currency_id",
    )
    earlydryer_wht_amount = fields.Monetary(
        string="WHT Withheld",
        compute="_compute_earlydryer_wht_amount",
        currency_field="company_currency_id",
        help="Withholding tax on this bill (positive), paid to the tax authority.",
    )
    earlydryer_opening_hash = fields.Char(readonly=True, copy=False, index=True)
    earlydryer_vat_registered = fields.Boolean(
        related="company_id.earlydryer_vat_registered"
    )

    @api.depends("journal_id", "move_type")
    def _compute_earlydryer_branch_id(self):
        context_branch = self.env.context.get("earlydryer_move_branch_id")
        default = self.env["earlydryer.branch.mixin"]._default_earlydryer_branch_id()
        for move in self:
            if move.earlydryer_branch_id:
                continue
            branch = move.journal_id.earlydryer_branch_id
            if context_branch:
                branch = self.env["earlydryer.branch"].browse(context_branch)
            if not branch and move.move_type != "entry":
                branch = default
            if branch and branch.company_id == (move.company_id or self.env.company):
                move.earlydryer_branch_id = branch
            else:
                move.earlydryer_branch_id = False

    def _compute_earlydryer_wht_deducted(self):
        for move in self:
            move.earlydryer_wht_deducted = sum(
                move.earlydryer_wht_deduction_ids.filtered(
                    lambda deduction: deduction.state == "posted"
                ).mapped("amount_total")
            )

    @api.depends("line_ids.balance", "line_ids.tax_line_id")
    def _compute_earlydryer_wht_amount(self):
        for move in self:
            lines = move.line_ids.filtered(
                lambda line: line.tax_line_id.earlydryer_wht_category_id
            )
            move.earlydryer_wht_amount = abs(sum(lines.mapped("balance")))

    # ------------------------------------------------------------------
    # Laundry jobs on the invoice (layout)
    # ------------------------------------------------------------------

    def _earlydryer_laundry_jobs(self):
        self.ensure_one()
        jobs = self.env["laundry.job"].sudo()
        sale_orders = self.invoice_line_ids.sale_line_ids.order_id
        if sale_orders:
            jobs |= sale_orders.sudo().laundry_job_ids
        pos_orders = self.sudo().pos_order_ids
        if pos_orders:
            jobs |= jobs.search([("pos_order_id", "in", pos_orders.ids)])
        return jobs

    def _earlydryer_invoice_bank_journals(self):
        self.ensure_one()
        return (
            self.env["account.journal"]
            .sudo()
            .search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("type", "=", "bank"),
                    ("earlydryer_show_on_invoice", "=", True),
                    ("bank_account_id", "!=", False),
                ]
            )
        )

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        to_submit = posted.filtered(
            lambda move: move.move_type in ("out_invoice", "out_refund")
            and move.company_id.earlydryer_einvoice_enabled
        )
        if to_submit:
            to_submit._earlydryer_einvoice_submit()
        return posted

    def _earlydryer_einvoice_submit(self):
        """Extension point of the FIRS e-invoicing integration (HELD).

        Called with the customer invoices and credit notes just posted, only
        when ``res.company.earlydryer_einvoice_enabled`` is set. The
        integration waits for Earlydryer's tax status and the FIRS
        requirements; a later module overrides this method.
        """
        return True

    # ------------------------------------------------------------------
    # WHT
    # ------------------------------------------------------------------

    def action_earlydryer_wht_deduction(self):
        self.ensure_one()
        if self.move_type != "out_invoice" or self.state != "posted":
            raise UserError(
                self.env._("Register a WHT deduction on a posted customer invoice.")
            )
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_accounting_ng.earlydryer_wht_deduction_wizard_action"
        )
        action["context"] = {"default_invoice_id": self.id}
        return action

    def action_earlydryer_wht_removal(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_accounting_ng.earlydryer_wht_removal_wizard_action"
        )
        action["context"] = {"default_move_id": self.id}
        return action

    def action_earlydryer_view_wht_deductions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("WHT Deductions"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("earlydryer_wht_invoice_id", "=", self.id)],
        }

    def action_earlydryer_wht_certificate_received(self):
        for move in self:
            if move.earlydryer_kind != "wht_deduction":
                continue
            move.earlydryer_wht_certificate_date = fields.Date.context_today(move)
        return True

    @api.model
    def _earlydryer_rider_handover(
        self, branch, amount, rider_employee, date=None, ref=None
    ):
        """Rider's cash collections handed over at the plant: Dr plant cash /
        Cr rider cash in transit. Called by the logistics module and the
        Rider handover wizard.

        :returns: the posted entry
        """
        branch.ensure_one()
        branch._earlydryer_check_cash_right("handover")
        branch = branch.sudo()
        if amount <= 0:
            raise UserError(self.env._("The handover amount must be positive."))
        journal = branch.cash_journal_id
        rider_account = branch.earlydryer_rider_account_id
        if not journal or not rider_account:
            raise UserError(
                self.env._(
                    "Run the accounting setup first: %(branch)s needs a plant cash "
                    "journal and a rider cash journal.",
                    branch=branch.display_name,
                )
            )
        label = self.env._(
            "Rider cash handover: %(rider)s", rider=rider_employee.sudo().name or "-"
        )
        move = (
            self.sudo()
            .with_context(earlydryer_move_branch_id=branch.id)
            .create(
                {
                    "move_type": "entry",
                    "journal_id": journal.id,
                    "date": date or fields.Date.context_today(self),
                    "ref": " - ".join(part for part in (label, ref) if part),
                    "earlydryer_branch_id": branch.id,
                    "earlydryer_kind": "rider_handover",
                    "earlydryer_rider_employee_id": rider_employee.id or False,
                    "line_ids": [
                        Command.create(
                            {
                                "name": label,
                                "account_id": journal.default_account_id.id,
                                "debit": amount,
                            }
                        ),
                        Command.create(
                            {
                                "name": label,
                                "account_id": rider_account.id,
                                "credit": amount,
                            }
                        ),
                    ],
                }
            )
        )
        move.action_post()
        return move

    @api.model_create_multi
    def create(self, vals_list):
        branch_id = self.env.context.get("earlydryer_move_branch_id")
        if branch_id:
            for vals in vals_list:
                vals.setdefault("earlydryer_branch_id", branch_id)
        return super().create(vals_list)
