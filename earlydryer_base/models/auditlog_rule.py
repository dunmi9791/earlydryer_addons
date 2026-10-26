# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class AuditlogRule(models.Model):
    _inherit = "auditlog.rule"

    def _patch_method(self, model, method_name, check_attr):
        """Patch ORM methods only once every module is loaded.

        auditlog sets the logging method on the model class, its ``origin``
        being the method resolved at that moment. When a rule is confirmed
        while modules are still loading (our post_init hooks), the model class
        is kept and extended by the modules loaded after, whose overrides of
        create/write/... are then skipped by the patched method until the
        server restarts. The rules confirmed meanwhile are patched by the
        ``_register_hook`` call Odoo makes on every model once loaded.
        """
        if not self.pool.loaded:
            return False
        return super()._patch_method(model, method_name, check_attr)
