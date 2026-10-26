# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

# notification type and subchannel of the stage board (see ir_websocket.py)
BOARD_SUBCHANNEL = "earlydryer_board"
BOARD_NOTIFICATION = "earlydryer.board/updated"
MACHINES_NOTIFICATION = "earlydryer.board/machines"


class EarlydryerBranch(models.Model):
    _name = "earlydryer.branch"
    # bus.listener.mixin: boards subscribe to (branch, "earlydryer_board")
    _inherit = ["earlydryer.branch", "bus.listener.mixin"]

    production_mode = fields.Selection(
        [
            ("front_desk", "Front Desk"),
            ("tablet", "Production Tablet"),
            ("both", "Both"),
        ],
        required=True,
        default="front_desk",
        help="Front Desk: the front desk moves the orders and picks who did "
        "the work. Production Tablet: staff identify themselves on a shared "
        "tablet (badge or PIN) and scan the garments they processed.",
    )
    board_refresh_seconds = fields.Integer(
        string="Board Refresh (s)",
        default=30,
        help="Polling interval of the stage board, used only when live "
        "updates are unavailable.",
    )
    tablet_idle_seconds = fields.Integer(
        string="Tablet Idle Time (s)",
        default=120,
        help="The tablet forgets the identified employee after this idle "
        "time and asks again.",
    )
    use_wash_batches = fields.Boolean(
        help="Record wash and dry loads (machine, program, weight, garments)."
    )
    batch_moves_stage = fields.Boolean(
        string="Finished Batch Moves Jobs",
        default=True,
        help="When a batch is done, jobs whose garments have all been through "
        "a finished batch move to Washed / Dried.",
    )
    require_load_weight = fields.Boolean(
        help="A batch cannot start without its load weight."
    )
    require_sorting_colour_group = fields.Boolean(
        default=True,
        help="Every garment needs a colour group before the job is Sorted.",
    )
    qc_reason_required = fields.Boolean(
        string="QC Reason Required",
        default=True,
        help="A failed garment needs a rework reason.",
    )
    wash_batch_sequence_id = fields.Many2one(
        "ir.sequence", string="Batch Sequence", readonly=True, copy=False
    )

    def _earlydryer_uses_tablet(self):
        self.ensure_one()
        return self.production_mode in ("tablet", "both")

    def _earlydryer_wash_batch_ensure_sequence(self):
        """Batch numbering per plant: <CODE>/WB/00001."""
        Sequence = self.env["ir.sequence"].sudo()
        for branch in self.filtered(lambda b: not b.wash_batch_sequence_id):
            branch.sudo().wash_batch_sequence_id = Sequence.create(
                {
                    "name": self.env._(
                        "Wash Batches %(branch)s", branch=branch.display_name
                    ),
                    "code": f"earlydryer.wash.batch.{branch.id}",
                    "prefix": f"{branch.code}/WB/",
                    "padding": 5,
                    "company_id": branch.company_id.id,
                }
            )
        return self.wash_batch_sequence_id

    @api.model_create_multi
    def create(self, vals_list):
        branches = super().create(vals_list)
        branches._earlydryer_wash_batch_ensure_sequence()
        return branches

    def write(self, vals):
        res = super().write(vals)
        if "code" in vals:
            for branch in self.filtered("wash_batch_sequence_id"):
                branch.wash_batch_sequence_id.sudo().prefix = f"{branch.code}/WB/"
        return res

    def _earlydryer_board_notify(self, jobs):
        """Tell the boards of each branch that ``jobs`` changed. Sent at commit
        (bus.bus precommit), so a refused move never notifies."""
        for branch in self:
            branch_jobs = jobs.filtered(lambda j, b=branch: j.earlydryer_branch_id == b)
            if branch_jobs:
                branch._bus_send(
                    BOARD_NOTIFICATION,
                    {"branch_id": branch.id, "job_ids": branch_jobs.ids},
                    subchannel=BOARD_SUBCHANNEL,
                )
