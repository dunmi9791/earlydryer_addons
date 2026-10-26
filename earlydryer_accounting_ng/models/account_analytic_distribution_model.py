# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class AccountAnalyticDistributionModel(models.Model):
    """Two more criteria: the plant of the document and the service line of
    the product. The setup wizard creates one model per plant (plant plan) and
    one per service line (service line plan); core merges one model per root
    plan, so a line gets both."""

    _inherit = "account.analytic.distribution.model"

    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        ondelete="cascade",
        check_company=True,
        help="Applies to lines of documents of this plant.",
    )
    earlydryer_service_line_id = fields.Many2one(
        "account.analytic.account",
        string="Service Line",
        ondelete="cascade",
        domain=lambda self: self.env[
            "earlydryer.service.type"
        ]._earlydryer_service_line_domain(),
        help="Applies to lines whose product belongs to this service line.",
    )

    def _get_default_search_domain_vals(self):
        return super()._get_default_search_domain_vals() | {
            "earlydryer_branch_id": False,
            "earlydryer_service_line_id": False,
        }
