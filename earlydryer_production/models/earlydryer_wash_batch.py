# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command, Domain

from .laundry_job_item import COLOUR_GROUPS
from .laundry_job_stage_log import SOURCE_CTX
from .maintenance_equipment import BATCH_MACHINE_TYPES

PRODUCTION_GROUP = "earlydryer_base.group_production"
MANAGER_GROUP = "earlydryer_base.group_branch_manager"
OPEN_BATCH_STATES = ("draft", "running")
# batch type -> (job state its garments wait in, job state once done)
BATCH_STAGES = {"wash": ("sorted", "washed"), "dry": ("washed", "dried")}
# what a finished or cancelled batch keeps (chatter fields stay writable)
LOCKED_FIELDS = {
    "batch_type",
    "machine_id",
    "colour_group",
    "service_type_id",
    "item_ids",
    "employee_id",
    "started_on",
    "finished_on",
    "load_weight_kg",
    "program",
    "earlydryer_branch_id",
}


class EarlydryerWashBatch(models.Model):
    """One machine load. Optional: plants with ``use_wash_batches`` only.

    No scheduling and no consumable posting: a batch records which garments
    went into which machine, run by whom, and moves the jobs whose garments
    have all been through a finished batch.
    """

    _name = "earlydryer.wash.batch"
    _description = "Earlydryer Wash / Dry Batch"
    _inherit = ["mail.thread", "earlydryer.branch.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Number",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env._("New"),
    )
    company_id = fields.Many2one(
        related="earlydryer_branch_id.company_id", store=True, index=True
    )
    batch_type = fields.Selection(
        [("wash", "Wash"), ("dry", "Dry")],
        string="Type",
        required=True,
        default="wash",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
    )
    machine_id = fields.Many2one(
        "maintenance.equipment",
        tracking=True,
        domain="[('earlydryer_branch_id', '=', earlydryer_branch_id), "
        "('earlydryer_machine_type', 'in', machine_type_ids)]",
    )
    machine_type_ids = fields.Json(compute="_compute_machine_type_ids")
    machine_status = fields.Selection(related="machine_id.earlydryer_status")
    machine_capacity_kg = fields.Float(related="machine_id.earlydryer_capacity_kg")
    colour_group = fields.Selection(COLOUR_GROUPS, tracking=True)
    service_type_id = fields.Many2one(
        "earlydryer.service.type", help="Optional grouping."
    )
    item_ids = fields.Many2many(
        "laundry.job.item",
        "earlydryer_wash_batch_item_rel",
        "batch_id",
        "item_id",
        string="Garments",
        copy=False,
        domain="[('earlydryer_branch_id', '=', earlydryer_branch_id), "
        "('job_state', '=', wait_state), ('missing', '=', False), "
        "('id', 'not in', busy_item_ids)]",
    )
    wait_state = fields.Char(compute="_compute_wait_state")
    busy_item_ids = fields.Many2many(
        "laundry.job.item", compute="_compute_busy_item_ids"
    )
    job_ids = fields.Many2many("laundry.job", compute="_compute_job_ids", string="Jobs")
    item_count = fields.Integer(compute="_compute_item_count", store=True)
    job_count = fields.Integer(compute="_compute_job_ids")
    estimated_weight_kg = fields.Float(
        string="Estimated Weight (kg)",
        compute="_compute_job_ids",
        digits=(16, 1),
        help="From the garment categories' average weight, when known.",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Run By",
        tracking=True,
        domain="[('earlydryer_branch_id', 'in', [earlydryer_branch_id, False])]",
    )
    started_on = fields.Datetime(readonly=True, copy=False)
    finished_on = fields.Datetime(readonly=True, copy=False)
    duration_minutes = fields.Integer(
        string="Duration (min)", compute="_compute_duration_minutes", store=True
    )
    load_weight_kg = fields.Float(
        string="Load Weight (kg)",
        digits=(16, 2),
        tracking=True,
        help="Weighed load, when the plant weighs its loads (cost per kg).",
    )
    require_load_weight = fields.Boolean(
        related="earlydryer_branch_id.require_load_weight"
    )
    program = fields.Char(help='e.g. "40 °C cotton"')
    note = fields.Text()
    override_note = fields.Text(
        string="Override Reason",
        copy=False,
        help="Branch Manager: why the batch may start on a machine that is "
        "down or already running.",
    )
    suggest_count = fields.Integer(
        string="Suggest up to",
        default=15,
        help="Garments to propose when the weights are not known.",
    )

    _load_weight_positive = models.Constraint(
        "CHECK(load_weight_kg >= 0)", "The load weight cannot be negative."
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends("batch_type")
    def _compute_machine_type_ids(self):
        for batch in self:
            batch.machine_type_ids = list(
                BATCH_MACHINE_TYPES[batch.batch_type or "wash"]
            )

    @api.depends("batch_type")
    def _compute_wait_state(self):
        for batch in self:
            batch.wait_state = BATCH_STAGES[batch.batch_type or "wash"][0]

    @api.depends("batch_type", "earlydryer_branch_id")
    def _compute_busy_item_ids(self):
        for batch in self:
            others = self.sudo().search(
                [
                    ("batch_type", "=", batch.batch_type),
                    ("state", "in", OPEN_BATCH_STATES),
                    ("earlydryer_branch_id", "=", batch.earlydryer_branch_id.id),
                    ("id", "!=", batch._origin.id or 0),
                ]
            )
            batch.busy_item_ids = others.item_ids.with_env(self.env)

    @api.depends("item_ids", "item_ids.garment_category_id.average_weight_kg")
    def _compute_job_ids(self):
        for batch in self:
            items = batch.item_ids
            batch.job_ids = items.job_id
            batch.job_count = len(items.job_id)
            batch.estimated_weight_kg = sum(
                items.mapped("garment_category_id.average_weight_kg")
            )

    @api.depends("item_ids")
    def _compute_item_count(self):
        for batch in self:
            batch.item_count = len(batch.item_ids)

    @api.depends("started_on", "finished_on")
    def _compute_duration_minutes(self):
        for batch in self:
            if batch.started_on and batch.finished_on:
                delta = batch.finished_on - batch.started_on
                batch.duration_minutes = int(delta.total_seconds() // 60)
            else:
                batch.duration_minutes = 0

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("item_ids", "state", "batch_type")
    def _check_items_single_open_batch(self):
        for batch in self.filtered(lambda b: b.state in OPEN_BATCH_STATES):
            if not batch.item_ids:
                continue
            other = self.sudo().search(
                [
                    ("id", "!=", batch.id),
                    ("batch_type", "=", batch.batch_type),
                    ("state", "in", OPEN_BATCH_STATES),
                    ("item_ids", "in", batch.item_ids.ids),
                ],
                limit=1,
            )
            if other:
                shared = batch.item_ids & other.item_ids
                raise ValidationError(
                    self.env._(
                        "%(items)s already in open batch %(batch)s.",
                        items=", ".join(shared.mapped("display_name")),
                        batch=other.name,
                    )
                )

    @api.constrains("item_ids", "earlydryer_branch_id")
    def _check_items_branch(self):
        for batch in self:
            if batch.item_ids.filtered(
                lambda i, b=batch: i.earlydryer_branch_id != b.earlydryer_branch_id
            ):
                raise ValidationError(
                    self.env._("A batch only holds garments of its own plant.")
                )

    @api.constrains("machine_id", "batch_type", "earlydryer_branch_id")
    def _check_machine(self):
        for batch in self.filtered("machine_id"):
            machine = batch.machine_id
            if machine.earlydryer_branch_id != batch.earlydryer_branch_id:
                raise ValidationError(
                    self.env._(
                        "Machine %(machine)s is not in plant %(branch)s.",
                        machine=machine.display_name,
                        branch=batch.earlydryer_branch_id.display_name,
                    )
                )
            if (
                machine.earlydryer_machine_type
                not in BATCH_MACHINE_TYPES[batch.batch_type]
            ):
                raise ValidationError(
                    self.env._(
                        "Machine %(machine)s cannot run a %(type)s batch.",
                        machine=machine.display_name,
                        type=dict(
                            self._fields["batch_type"]._description_selection(self.env)
                        )[batch.batch_type],
                    )
                )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        self._earlydryer_check_right()
        batches = super().create(vals_list)
        for batch in batches:
            branch = batch.earlydryer_branch_id
            if not branch.use_wash_batches:
                raise UserError(
                    self.env._(
                        "Plant %(branch)s does not use wash batches.",
                        branch=branch.display_name,
                    )
                )
            sequence = branch._earlydryer_wash_batch_ensure_sequence()
            batch.name = sequence.sudo().next_by_id()
        return batches

    def write(self, vals):
        self._earlydryer_check_right()
        closed = self.filtered(lambda b: b.state in ("done", "cancelled"))
        if closed and not self.env.su and set(vals) & LOCKED_FIELDS:
            raise UserError(self.env._("A finished or cancelled batch cannot change."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if self.filtered(lambda b: b.state == "done"):
            raise UserError(self.env._("A finished batch cannot be deleted."))

    @api.model
    def _earlydryer_check_right(self):
        if self.env.su or self.env.user.has_group(PRODUCTION_GROUP):
            return
        raise AccessError(
            self.env._("Only production staff, QC and managers run batches.")
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _earlydryer_check_startable(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(
                self.env._("Batch %(batch)s is not a draft.", batch=self.name)
            )
        if not self.machine_id:
            raise UserError(self.env._("Choose the machine."))
        if not self.item_ids:
            raise UserError(self.env._("Add the garments of the load."))
        if not self.employee_id:
            raise UserError(self.env._("Record who runs the batch."))
        wait_state = BATCH_STAGES[self.batch_type][0]
        waiting = self.item_ids.filtered(lambda i: i.job_state != wait_state)
        if waiting:
            raise UserError(
                self.env._(
                    "These garments are not waiting for this batch: %(items)s.",
                    items=", ".join(waiting.mapped("display_name")),
                )
            )
        if self.earlydryer_branch_id.require_load_weight and not self.load_weight_kg:
            raise UserError(self.env._("Weigh the load and enter its weight first."))
        problems = []
        status = self.machine_id.earlydryer_status
        if status == "down":
            problems.append(
                self.env._("Machine %(machine)s is down.", machine=self.machine_id.name)
            )
        if self.search_count(
            [("machine_id", "=", self.machine_id.id), ("state", "=", "running")]
        ):
            problems.append(
                self.env._(
                    "Machine %(machine)s is already running a batch.",
                    machine=self.machine_id.name,
                )
            )
        if problems:
            if not self.env.user.has_group(MANAGER_GROUP) and not self.env.su:
                raise UserError(
                    " ".join(problems)
                    + " "
                    + self.env._("Ask a Branch Manager to override.")
                )
            if not (self.override_note or "").strip():
                raise UserError(
                    " ".join(problems)
                    + " "
                    + self.env._("Give the override reason to start anyway.")
                )
            self.message_post(
                body=Markup("%s<br/>%s")
                % (
                    self.env._(
                        "Started by %(user)s despite: %(problems)s",
                        user=self.env.user.name,
                        problems=" ".join(problems),
                    ),
                    self.override_note,
                ),
                subtype_xmlid="mail.mt_note",
            )

    def action_start(self):
        for batch in self:
            batch._earlydryer_check_startable()
            batch.write({"state": "running", "started_on": fields.Datetime.now()})
        return True

    def action_done(self):
        for batch in self:
            if batch.state != "running":
                raise UserError(
                    self.env._("Batch %(batch)s is not running.", batch=batch.name)
                )
            batch.write({"state": "done", "finished_on": fields.Datetime.now()})
            if batch.earlydryer_branch_id.batch_moves_stage:
                batch._earlydryer_move_covered_jobs()
        return True

    def action_cancel(self):
        for batch in self:
            if batch.state == "done":
                raise UserError(
                    self.env._("Batch %(batch)s is done.", batch=batch.name)
                )
            batch.state = "cancelled"
        return True

    def action_reset_draft(self):
        self.filtered(lambda b: b.state == "cancelled").write({"state": "draft"})
        return True

    # ------------------------------------------------------------------
    # Coverage of the jobs
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_covered_items(self, job, batch_type):
        """Items of ``job`` through a finished ``batch_type`` batch since the
        job last entered the waiting stage (a QC rework starts again)."""
        wait_state = BATCH_STAGES[batch_type][0]
        last_entry = (
            self.env["laundry.job.stage.log"]
            .sudo()
            .search(
                [("job_id", "=", job.id), ("to_state", "=", wait_state)],
                order="date desc, id desc",
                limit=1,
            )
        )
        domain = Domain(
            [
                ("batch_type", "=", batch_type),
                ("state", "=", "done"),
                ("item_ids", "in", job.item_ids.ids),
            ]
        )
        if last_entry:
            domain &= Domain("finished_on", ">=", last_entry.date)
        batches = self.sudo().search(domain)
        return batches.item_ids & job.item_ids.sudo()

    @api.model
    def _earlydryer_job_progress(self, job, batch_type):
        """``(done, total)`` garments of ``job`` for ``batch_type`` batches."""
        target_state = BATCH_STAGES[batch_type][1]
        needed = job.item_ids.sudo()._earlydryer_needs_stage(target_state)
        covered = self._earlydryer_covered_items(job, batch_type) & needed
        return len(covered), len(needed)

    def _earlydryer_move_covered_jobs(self):
        """Move the jobs of this finished batch whose garments needing the
        stage are all covered by finished batches. Others stay put."""
        self.ensure_one()
        wait_state, target_state = BATCH_STAGES[self.batch_type]
        moved = self.env["laundry.job"]
        for job in self.item_ids.job_id:
            if job.state != wait_state:
                continue
            done, total = self._earlydryer_job_progress(job, self.batch_type)
            if done < total:
                continue
            items = self.item_ids.filtered(lambda i, j=job: i.job_id == j)
            try:
                with self.env.cr.savepoint():
                    job.with_context(**{SOURCE_CTX: "batch"}).action_move_to(
                        target_state, employee=self.employee_id, items=items
                    )
                moved |= job
            except (UserError, AccessError, ValidationError) as error:
                self.message_post(
                    body=self.env._(
                        "Job %(job)s could not move: %(error)s",
                        job=job.name,
                        error=error.args[0] if error.args else error,
                    ),
                    subtype_xmlid="mail.mt_note",
                )
        if moved:
            self.message_post(
                body=self.env._(
                    "Moved to %(stage)s: %(jobs)s",
                    stage=moved[:1]._earlydryer_state_label(target_state),
                    jobs=", ".join(moved.mapped("name")),
                ),
                subtype_xmlid="mail.mt_note",
            )
        return moved

    # ------------------------------------------------------------------
    # Suggestion
    # ------------------------------------------------------------------

    def _earlydryer_suggest_items(self):
        """Waiting garments for this batch: express first, then oldest, up to
        the machine capacity when every weight is known, otherwise up to
        ``suggest_count``. A proposal only: nothing is scheduled."""
        self.ensure_one()
        wait_state, target_state = BATCH_STAGES[self.batch_type]
        Item = self.env["laundry.job.item"]
        domain = [
            ("earlydryer_branch_id", "=", self.earlydryer_branch_id.id),
            ("job_state", "=", wait_state),
            ("missing", "=", False),
            ("id", "not in", self.busy_item_ids.ids),
        ]
        if self.colour_group:
            domain.append(("colour_group", "=", self.colour_group))
        if self.service_type_id:
            domain.append(("service_type_id", "=", self.service_type_id.id))
        candidates = Item.search(domain)._earlydryer_needs_stage(target_state)
        covered = Item.browse()
        for job in candidates.job_id:
            covered |= self._earlydryer_covered_items(job, self.batch_type)
        candidates = (candidates - covered).sorted(
            lambda i: (not i.job_id.express, i.job_id.received_on, i.job_id.id, i.id)
        )
        capacity = self.machine_id.earlydryer_capacity_kg
        weights = candidates.mapped("garment_category_id.average_weight_kg")
        selected = self.item_ids
        if capacity and candidates and all(weights):
            load = sum(selected.mapped("garment_category_id.average_weight_kg"))
            for item in candidates - selected:
                weight = item.garment_category_id.average_weight_kg
                if load + weight > capacity:
                    break
                selected |= item
                load += weight
        else:
            room = max(self.suggest_count - len(selected), 0)
            selected |= (candidates - selected)[:room]
        return selected

    def action_suggest_items(self):
        for batch in self:
            if batch.state != "draft":
                raise UserError(self.env._("Only a draft batch can be filled."))
            if not batch.machine_id:
                raise UserError(self.env._("Choose the machine first."))
            batch.item_ids = [Command.set(batch._earlydryer_suggest_items().ids)]
        return True
