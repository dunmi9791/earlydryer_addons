# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models


class IrRule(models.Model):
    _inherit = "ir.rule"

    @api.model
    def _eval_context(self):
        """Expose the user's allowed branches to record rule domains.

        Reading ``user.earlydryer_branch_ids`` inside a rule on
        ``earlydryer.branch`` would apply that same rule again while reading
        the many2many (recursion), so the ids are read with sudo here, the way
        core exposes ``company_ids``.
        """
        context = super()._eval_context()
        context["earlydryer_branch_ids"] = (
            self.env.user.sudo()
            .with_context(active_test=False)
            .earlydryer_branch_ids.ids
        )
        return context
