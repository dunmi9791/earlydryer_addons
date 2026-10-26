# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EarlydryerBranchMixin(models.AbstractModel):
    """Make a document belong to an Earlydryer branch.

    Inheriting models get a required ``earlydryer_branch_id`` defaulting to
    the user's default branch. The field is tracked, so inheriting models
    should also inherit ``mail.thread`` (otherwise Odoo warns about the
    ``tracking`` parameter).

    Branch security is NOT automatic: each inheriting model must declare its
    own record rules, following ``security/earlydryer_rules.xml``::

        <record id="my_model_rule_branch" model="ir.rule">
            <field name="name">My model: allowed branches</field>
            <field name="model_id" ref="model_my_model"/>
            <field name="domain_force">
                [('earlydryer_branch_id', 'in', earlydryer_branch_ids)]
            </field>
            <field name="groups" eval="[(4, ref('base.group_user'))]"/>
        </record>
        <record id="my_model_rule_all_branches" model="ir.rule">
            <field name="name">My model: all branches</field>
            <field name="model_id" ref="model_my_model"/>
            <field name="domain_force">[(1, '=', 1)]</field>
            <field name="groups"
                   eval="[(4, ref('earlydryer_base.group_all_branches'))]"/>
        </record>

    ``earlydryer_branch_ids`` is added to the record rule evaluation context
    by this module (see ``models/ir_rule.py``).
    """

    _name = "earlydryer.branch.mixin"
    _description = "Earlydryer Branch Mixin"

    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Branch",
        required=True,
        index=True,
        tracking=True,
        ondelete="restrict",
        default=lambda self: self._default_earlydryer_branch_id(),
    )

    @api.model
    def _default_earlydryer_branch_id(self):
        user = self.env.user.sudo()
        branches = user.earlydryer_branch_ids.filtered(
            lambda b: b.company_id in self.env.companies
        )
        default = user.earlydryer_branch_id
        if default and default in branches:
            return default
        if len(branches) == 1:
            return branches
        return self.env["earlydryer.branch"]

    @api.constrains(
        lambda self: (
            ["earlydryer_branch_id"]
            + (["company_id"] if "company_id" in self._fields else [])
        )
    )
    def _check_earlydryer_branch_company(self):
        if "company_id" not in self._fields:
            return
        for record in self:
            branch = record.earlydryer_branch_id
            if record.company_id and branch and branch.company_id != record.company_id:
                raise ValidationError(
                    self.env._(
                        "Branch %(branch)s belongs to company %(branch_company)s, "
                        "not to %(company)s.",
                        branch=branch.display_name,
                        branch_company=branch.company_id.display_name,
                        company=record.company_id.display_name,
                    )
                )

    @api.model
    def _earlydryer_branch_domain(self, field_name="earlydryer_branch_id"):
        """Domain on ``field_name`` for the branches the current user can see."""
        return self.env["res.users"]._earlydryer_branch_domain(field_name)
