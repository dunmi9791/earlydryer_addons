# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import AccessError

ADMIN_GROUP = "earlydryer_base.group_admin"

SCAN_MODES = [
    ("find", "Find"),
    ("move", "Move"),
    ("pack", "Pack"),
    ("assign", "Assign"),
]
SCAN_RESULTS = [
    ("ok", "OK"),
    ("duplicate", "Already Scanned"),
    ("wrong_job", "Wrong Job"),
    ("wrong_branch", "Wrong Plant"),
    ("unknown", "Unknown"),
    ("invalid", "Invalid Code"),
    ("refused", "Refused"),
]
MISMATCH_RESULTS = ("wrong_job", "wrong_branch")


class EarlydryerScanLog(models.Model):
    """One row per barcode scan through the scan API. Append-only."""

    _name = "earlydryer.scan.log"
    _description = "Earlydryer Scan Log"
    _order = "date desc, id desc"
    _rec_name = "code"
    _log_access = False

    date = fields.Datetime(
        required=True, index=True, default=fields.Datetime.now, readonly=True
    )
    code = fields.Char(required=True, readonly=True)
    mode = fields.Selection(SCAN_MODES, required=True, index=True, readonly=True)
    result = fields.Selection(SCAN_RESULTS, required=True, index=True, readonly=True)
    is_mismatch = fields.Boolean(
        string="Mismatch",
        compute="_compute_is_mismatch",
        store=True,
        help="A garment of another job or plant was scanned at packing.",
    )
    job_id = fields.Many2one(
        "laundry.job",
        string="Scanned Job",
        index="btree_not_null",
        ondelete="set null",
        readonly=True,
        help="Job of the scanned code.",
    )
    item_id = fields.Many2one(
        "laundry.job.item", ondelete="set null", readonly=True, string="Scanned Item"
    )
    expected_job_id = fields.Many2one(
        "laundry.job",
        index="btree_not_null",
        ondelete="set null",
        readonly=True,
        help="Job being packed when the scan was a mismatch.",
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        index=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    employee_id = fields.Many2one("hr.employee", ondelete="set null", readonly=True)
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        index=True,
        ondelete="set null",
        readonly=True,
        help="Plant where the scan happened.",
    )
    message = fields.Char(readonly=True)

    @api.depends("result", "mode")
    def _compute_is_mismatch(self):
        for log in self:
            log.is_mismatch = log.mode == "pack" and log.result in MISMATCH_RESULTS

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group(ADMIN_GROUP):
            raise AccessError(self.env._("Scan log rows cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_not_admin(self):
        if not self.env.su and not self.env.user.has_group(ADMIN_GROUP):
            raise AccessError(
                self.env._("Only an Earlydryer Administrator can delete scan log rows.")
            )
