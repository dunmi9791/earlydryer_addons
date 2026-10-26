# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models

from .pos_order import NO_AUTO_TAG_CTX


class LaundryJobItem(models.Model):
    _inherit = "laundry.job.item"

    earlydryer_tag_conflict = fields.Char(
        string="Tag Conflict",
        readonly=True,
        copy=False,
        help="The tag code printed or scanned at the till was refused when the "
        "order synced: tag the item again.",
    )

    def _earlydryer_auto_assign_tags(self):
        # POS jobs keep the codes the till printed: items left without one are
        # tagged at the counter or from the backend, never renumbered here
        if self.env.context.get(NO_AUTO_TAG_CTX):
            return
        return super()._earlydryer_auto_assign_tags()

    def _earlydryer_check_locked(self, jobs, fnames=None):
        # the conflict note is cleared when the item is tagged after intake
        if fnames is not None:
            fnames = set(fnames) - {"earlydryer_tag_conflict"}
        return super()._earlydryer_check_locked(jobs, fnames)

    def write(self, vals):
        if vals.get("tag_code") and any(self.mapped("earlydryer_tag_conflict")):
            vals = dict(vals, earlydryer_tag_conflict=False)
        return super().write(vals)
