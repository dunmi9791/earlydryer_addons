# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import AccessError

ADMIN_GROUP = "earlydryer_base.group_admin"


class EarlydryerTagHistory(models.Model):
    """A tag replaced on a garment (lost or damaged). Never edited.

    In printed mode the old code stays reserved: no other garment can get it.
    """

    _name = "earlydryer.tag.history"
    _description = "Earlydryer Replaced Garment Tag"
    _order = "date desc, id desc"
    _rec_name = "old_code"

    item_id = fields.Many2one(
        "laundry.job.item", required=True, index=True, ondelete="cascade", readonly=True
    )
    job_id = fields.Many2one(related="item_id.job_id", store=True, index=True)
    earlydryer_branch_id = fields.Many2one(
        related="item_id.earlydryer_branch_id", store=True, index=True
    )
    company_id = fields.Many2one(related="item_id.company_id", store=True)
    old_code = fields.Char(required=True, index=True, readonly=True)
    new_code = fields.Char(readonly=True)
    reason = fields.Text(required=True, readonly=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one(
        "res.users",
        string="Replaced By",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )

    def _earlydryer_check_admin(self):
        if not self.env.su and not self.env.user.has_group(ADMIN_GROUP):
            raise AccessError(self.env._("The tag history cannot be changed."))

    def write(self, vals):
        self._earlydryer_check_admin()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_not_admin(self):
        self._earlydryer_check_admin()
