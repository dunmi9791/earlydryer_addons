# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models
from odoo.exceptions import UserError


class EarlydryerBranch(models.Model):
    _inherit = "earlydryer.branch"

    earlydryer_pricelist_ids = fields.One2many(
        "product.pricelist", "earlydryer_branch_id", string="Price Lists"
    )

    def _earlydryer_pos_pricelists(self):
        """(default, available) price lists of the plant's points of sale.

        Default: the walk-in price list of the plant (or the channel-only
        one). Available: the default plus every active corporate contract
        list valid in this plant, so contract clients are priced offline.
        """
        self.ensure_one()
        Pricelist = self.env["product.pricelist"].with_company(self.company_id)
        walk_in = Pricelist.search(
            [
                ("earlydryer_channel", "=", "walk_in"),
                ("earlydryer_is_contract", "=", False),
                ("company_id", "in", [self.company_id.id, False]),
                ("earlydryer_branch_id", "in", [self.id, False]),
            ],
            # the plant's own list first, then the channel-only one
            order="earlydryer_branch_id, sequence, id",
            limit=1,
        )
        contracts = Pricelist.search(
            [
                ("earlydryer_is_contract", "=", True),
                ("company_id", "in", [self.company_id.id, False]),
                ("earlydryer_branch_id", "in", [self.id, False]),
            ]
        )
        return walk_in, walk_in | contracts

    def action_earlydryer_sync_pos_pricelists(self):
        """Set the default and available price lists on the plant's POS configs."""
        for branch in self:
            if not branch.pos_config_ids:
                raise UserError(
                    self.env._(
                        "Branch %(branch)s has no point of sale.",
                        branch=branch.display_name,
                    )
                )
            default, available = branch._earlydryer_pos_pricelists()
            if default.earlydryer_channel != "walk_in":
                raise UserError(
                    self.env._(
                        "There is no walk-in price list for %(branch)s.",
                        branch=branch.display_name,
                    )
                )
            branch.pos_config_ids.write(
                {
                    "use_pricelist": True,
                    "pricelist_id": default.id,
                    "available_pricelist_ids": [fields.Command.set(available.ids)],
                }
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._("Point of sale price lists updated."),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
