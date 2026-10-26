# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class EarlydryerWalletCreditWizard(models.TransientModel):
    _name = "earlydryer.wallet.credit.wizard"
    _description = "Credit a Customer Wallet"

    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount = fields.Monetary(required=True)
    reason = fields.Text(required=True, help="Goodwill gesture, claim outcome...")
    laundry_job_id = fields.Many2one(
        "laundry.job",
        domain="[('partner_id', 'child_of', partner_id)]",
    )
    reference = fields.Char(string="Claim Reference")
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Branch",
        default=lambda self: self.env.user.earlydryer_branch_id,
    )

    def action_confirm(self):
        self.ensure_one()
        self.env["earlydryer.wallet"]._earlydryer_check_right("credit")
        tx = self.env["earlydryer.wallet.transaction"]._earlydryer_new(
            self.partner_id,
            "credit",
            self.amount,
            company=self.company_id,
            reason=self.reason,
            reference=self.reference,
            laundry_job_id=self.laundry_job_id.id,
            earlydryer_branch_id=(
                self.laundry_job_id.earlydryer_branch_id or self.earlydryer_branch_id
            ).id,
            source="claim" if self.reference else "backend",
        )
        tx._earlydryer_submit()
        return {
            "type": "ir.actions.act_window",
            "res_model": tx._name,
            "res_id": tx.id,
            "view_mode": "form",
        }
