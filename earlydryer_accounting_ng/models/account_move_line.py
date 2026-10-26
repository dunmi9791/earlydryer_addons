# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

# accounts whose posted lines must carry a plant analytic (P&L by plant)
GAP_ACCOUNT_TYPES = (
    "income",
    "income_other",
    "expense",
    "expense_direct_cost",
    "expense_depreciation",
)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    earlydryer_branch_id = fields.Many2one(
        related="move_id.earlydryer_branch_id",
        store=True,
        index="btree_not_null",
        string="Plant",
    )
    earlydryer_analytic_gap = fields.Boolean(
        string="Missing Plant Analytic",
        compute="_compute_earlydryer_analytic_gap",
        store=True,
        index=True,
        help="A posted income or expense line without a plant analytic account: "
        "listed in Analytic Gaps for Finance (a warning, never a block).",
    )

    @api.depends("analytic_distribution", "account_id.account_type", "parent_state")
    def _compute_earlydryer_analytic_gap(self):
        plan = self.env.ref(
            "earlydryer_accounting_ng.analytic_plan_plants", raise_if_not_found=False
        )
        plant_ids = set()
        if plan:
            plant_ids = set(
                self.env["account.analytic.account"]
                .sudo()
                .with_context(active_test=False)
                .search([("root_plan_id", "=", plan.id)])
                .ids
            )
        for line in self:
            if (
                line.parent_state != "posted"
                or line.account_id.account_type not in GAP_ACCOUNT_TYPES
                or line.display_type in ("line_section", "line_note")
            ):
                line.earlydryer_analytic_gap = False
                continue
            ids = {
                int(account_id)
                for key in (line.analytic_distribution or {})
                for account_id in key.split(",")
                if account_id.strip().isdigit()
            }
            line.earlydryer_analytic_gap = not ids & plant_ids

    # ------------------------------------------------------------------
    # Analytic distribution: plant and service line criteria
    # ------------------------------------------------------------------

    def _earlydryer_service_line(self):
        """Service line of the product; surcharge and express lines take the
        one of the garment line they belong to."""
        self.ensure_one()
        product = self.product_id.sudo()
        if product.earlydryer_kind in ("surcharge", "express"):
            parent = self.sale_line_ids.sudo().earlydryer_parent_line_id[:1]
            if parent:
                return parent.product_id.earlydryer_service_line_id
        return product.earlydryer_service_line_id

    @api.depends("move_id.earlydryer_branch_id")
    def _compute_analytic_distribution(self):
        return super()._compute_analytic_distribution()

    def _get_analytic_distribution_arguments(self, root_plans):
        arguments = super()._get_analytic_distribution_arguments(root_plans)
        arguments["earlydryer_branch_id"] = self.move_id.earlydryer_branch_id.id
        arguments["earlydryer_service_line_id"] = self._earlydryer_service_line().id
        return arguments

    # ------------------------------------------------------------------
    # WHT on vendor bills
    # ------------------------------------------------------------------

    def _earlydryer_expected_wht(self):
        """The WHT tax this bill line should carry (vendor's category and type)."""
        self.ensure_one()
        move = self.move_id
        if (
            move.move_type not in ("in_invoice", "in_refund")
            or self.display_type != "product"
            or not move.partner_id
        ):
            return self.env["account.tax"]
        return move.partner_id.sudo()._earlydryer_wht_tax(move.company_id)

    def _get_computed_taxes(self):
        taxes = super()._get_computed_taxes()
        wht = self._earlydryer_expected_wht()
        if wht:
            taxes |= wht
        return taxes

    def _earlydryer_wht_taxes(self):
        return self.tax_ids.filtered("earlydryer_wht_category_id")

    def write(self, vals):
        if "tax_ids" not in vals or self.env.context.get("earlydryer_wht_reason"):
            return super().write(vals)
        before = {line.id: line._earlydryer_wht_taxes() for line in self}
        res = super().write(vals)
        removed = self.filtered(
            lambda line: line.move_id.move_type in ("in_invoice", "in_refund")
            and (before[line.id] - line.tax_ids)
            and line._earlydryer_expected_wht() in before[line.id] - line.tax_ids
        )
        if removed:
            raise UserError(
                self.env._(
                    "Remove the withholding tax with the 'Remove WHT' button of the "
                    "bill, which logs the reason (Finance only)."
                )
            )
        return res

    def _earlydryer_remove_wht(self, reason):
        """Take the WHT tax off these bill lines and log ``reason``."""
        user = self.env.user
        if not (
            self.env.su
            or user.has_group("earlydryer_base.group_finance")
            or user.has_group("earlydryer_base.group_admin")
        ):
            raise UserError(self.env._("Only Finance may remove withholding tax."))
        if not (reason or "").strip():
            raise UserError(self.env._("Give the reason for removing the WHT."))
        for move, lines in self.grouped("move_id").items():
            if move.state != "draft":
                raise UserError(
                    self.env._("Reset %(move)s to draft first.", move=move.display_name)
                )
            removed = []
            for line in lines:
                wht = line._earlydryer_wht_taxes()
                if not wht:
                    continue
                line.with_context(earlydryer_wht_reason=reason).write(
                    {"tax_ids": [(3, tax.id) for tax in wht]}
                )
                removed.append(f"{line.name or line.product_id.display_name}: {', '.join(wht.mapped('name'))}")
            if removed:
                move.message_post(
                    body=Markup("%s<br/>%s<ul>%s</ul>")
                    % (
                        self.env._("Withholding tax removed. Reason: %(reason)s", reason=reason),
                        self.env._("Lines:"),
                        Markup("").join(Markup("<li>%s</li>") % item for item in removed),
                    )
                )
        return True
