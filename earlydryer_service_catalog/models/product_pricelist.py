# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

EARLYDRYER_CHANNELS = [
    ("walk_in", "Walk-in"),
    ("pickup", "Pickup & Delivery"),
    ("corporate", "Corporate"),
]


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        index=True,
        ondelete="restrict",
        help="Leave empty for a price list valid in every plant.",
    )
    earlydryer_channel = fields.Selection(
        EARLYDRYER_CHANNELS,
        string="Channel",
        index=True,
        help="Set on every Earlydryer price list. Price lists without a "
        "channel are not used by the Earlydryer price resolution, except as "
        "the company default.",
    )
    earlydryer_is_contract = fields.Boolean(
        string="Corporate Contract",
        help="Negotiated price list of a corporate client. Set it as the "
        "client's price list; it then wins over the plant and channel lists.",
    )

    _earlydryer_branch_channel_uniq = models.UniqueIndex(
        "(COALESCE(earlydryer_branch_id, 0), earlydryer_channel, "
        "COALESCE(company_id, 0)) WHERE active AND earlydryer_channel IS NOT NULL "
        "AND earlydryer_is_contract IS NOT TRUE",
        "There is already an active price list for this plant and channel.",
    )

    @api.constrains(
        "earlydryer_branch_id", "earlydryer_channel", "earlydryer_is_contract"
    )
    def _check_earlydryer_channel(self):
        for pricelist in self:
            if (
                pricelist.earlydryer_is_contract
                and pricelist.earlydryer_channel != "corporate"
            ):
                raise ValidationError(
                    self.env._(
                        "%(pricelist)s: a corporate contract price list must use "
                        "the Corporate channel.",
                        pricelist=pricelist.display_name,
                    )
                )
            if pricelist.earlydryer_branch_id and not pricelist.earlydryer_channel:
                raise ValidationError(
                    self.env._(
                        "%(pricelist)s: set a channel on a plant price list.",
                        pricelist=pricelist.display_name,
                    )
                )
            branch_company = pricelist.earlydryer_branch_id.company_id
            if branch_company and pricelist.company_id not in (
                branch_company,
                self.env["res.company"],
            ):
                raise ValidationError(
                    self.env._(
                        "%(pricelist)s: the plant belongs to another company.",
                        pricelist=pricelist.display_name,
                    )
                )

    @api.onchange("earlydryer_is_contract")
    def _onchange_earlydryer_is_contract(self):
        if self.earlydryer_is_contract:
            self.earlydryer_channel = "corporate"

    @api.model
    def _earlydryer_company_default(self, company):
        """The company default price list (never an Earlydryer one)."""
        domain = [
            ("company_id", "in", [company.id, False]),
            ("earlydryer_channel", "=", False),
            ("earlydryer_is_contract", "=", False),
        ]
        param = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(f"res.partner.property_product_pricelist_{company.id}")
        )
        if param and param.isdigit():
            pricelist = self.search([*domain, ("id", "=", int(param))], limit=1)
            if pricelist:
                return pricelist
        return self.search(domain, order="sequence, id", limit=1)

    @api.model
    def _earlydryer_resolve_pricelist(self, partner, branch, channel, date=None):
        """Return the price list to use for an Earlydryer sale.

        1. the commercial partner's price list when it is a corporate contract;
        2. the price list of (``branch``, ``channel``);
        3. the price list of (no branch, ``channel``);
        4. the company default price list (a warning is logged).

        ``date`` is accepted for later modules (contract validity); price list
        items are filtered by date when computing prices, not here. Returns
        a ``product.pricelist`` recordset (possibly empty if the company has
        no price list at all: prices then fall back to the product price).
        """
        company = branch.company_id if branch else self.env.company
        Pricelist = self.with_company(company)
        if partner:
            contract = partner.commercial_partner_id.with_company(
                company
            ).property_product_pricelist
            if (
                contract.earlydryer_is_contract
                and contract.active
                and contract.company_id in (company, self.env["res.company"])
                and (
                    not contract.earlydryer_branch_id
                    or contract.earlydryer_branch_id == branch
                )
            ):
                return contract
        base_domain = [
            ("earlydryer_channel", "=", channel),
            ("earlydryer_is_contract", "=", False),
            ("company_id", "in", [company.id, False]),
        ]
        if branch:
            pricelist = Pricelist.search(
                [*base_domain, ("earlydryer_branch_id", "=", branch.id)],
                order="sequence, id",
                limit=1,
            )
            if pricelist:
                return pricelist
        pricelist = Pricelist.search(
            [*base_domain, ("earlydryer_branch_id", "=", False)],
            order="sequence, id",
            limit=1,
        )
        if pricelist:
            return pricelist
        pricelist = Pricelist._earlydryer_company_default(company)
        _logger.warning(
            "No Earlydryer price list for branch %s and channel %s; using the "
            "company default price list %s.",
            branch.display_name if branch else "-",
            channel,
            pricelist.display_name or "(none)",
        )
        return pricelist

    def action_earlydryer_new_version(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("New Price Version"),
            "res_model": "earlydryer.pricelist.version.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_pricelist_id": self.id},
        }
