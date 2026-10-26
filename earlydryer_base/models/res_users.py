# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class ResUsers(models.Model):
    _inherit = "res.users"

    earlydryer_branch_ids = fields.Many2many(
        "earlydryer.branch",
        "earlydryer_branch_res_users_rel",
        "user_id",
        "branch_id",
        string="Allowed Branches",
        help="Earlydryer branches (plants) this user works on.",
    )
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Default Branch",
        domain="[('id', 'in', earlydryer_branch_ids)]",
        help="Branch proposed by default on new Earlydryer documents.",
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            "earlydryer_branch_id",
            "earlydryer_branch_ids",
        ]

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ["earlydryer_branch_id"]

    def _get_invalidation_fields(self):
        # record rules are evaluated with the allowed branches and cached:
        # clear the registry cache like core does for company_ids
        return super()._get_invalidation_fields() | {"earlydryer_branch_ids"}

    @api.constrains("earlydryer_branch_id", "earlydryer_branch_ids")
    def _check_earlydryer_branch_id(self):
        for user in self.sudo():
            branch = user.earlydryer_branch_id
            if branch and branch not in user.earlydryer_branch_ids:
                raise ValidationError(
                    self.env._(
                        "The default branch %(branch)s of %(user)s must be one "
                        "of their allowed branches.",
                        branch=branch.display_name,
                        user=user.display_name,
                    )
                )

    @api.onchange("earlydryer_branch_ids")
    def _onchange_earlydryer_branch_ids(self):
        for user in self:
            if user.earlydryer_branch_id not in user.earlydryer_branch_ids._origin:
                user.earlydryer_branch_id = False
            if not user.earlydryer_branch_id and len(user.earlydryer_branch_ids) == 1:
                user.earlydryer_branch_id = user.earlydryer_branch_ids._origin

    def _earlydryer_has_all_branches(self):
        self.ensure_one()
        return self._has_group("earlydryer_base.group_all_branches")

    def _earlydryer_allowed_branches(self):
        """Branches the user can work on (all branches with group_all_branches)."""
        self.ensure_one()
        Branch = self.env["earlydryer.branch"].sudo()
        if self._earlydryer_has_all_branches():
            return Branch.search([])  # pylint: disable=no-search-all
        return self.sudo().earlydryer_branch_ids

    @api.model
    def _earlydryer_branch_domain(self, field_name="earlydryer_branch_id"):
        user = self.env.user
        if user._earlydryer_has_all_branches():
            return Domain.TRUE
        branch_ids = user.sudo().with_context(active_test=False).earlydryer_branch_ids
        return Domain(field_name, "in", branch_ids.ids)
