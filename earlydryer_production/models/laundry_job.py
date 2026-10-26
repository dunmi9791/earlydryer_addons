# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import UTC, datetime, time, timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import format_datetime
from odoo.tools.misc import clean_context

from odoo.addons.earlydryer_laundry_order.models.laundry_job import (
    FINAL_STATES,
    FORWARD_PATH,
    PRODUCTION_STATES,
    REWORK_STATES,
    TODO_ACTIVITY,
)

from ..hooks import set_service_colour_groups
from .earlydryer_wash_batch import BATCH_STAGES
from .laundry_job_stage_log import SOURCE_CTX

FRONT_DESK_GROUP = "earlydryer_base.group_front_desk"
PRODUCTION_GROUP = "earlydryer_base.group_production"
QC_GROUP = "earlydryer_base.group_qc"
MANAGER_GROUP = "earlydryer_base.group_branch_manager"
ALL_BRANCHES_GROUP = "earlydryer_base.group_all_branches"
# Production Staff (without Front Desk or QC) stop before these stages
PRODUCTION_FORBIDDEN_STATES = {
    "packed",
    "ready",
    "out_for_delivery",
    "delivered",
    "collected",
    "uncollected",
    "cancelled",
}
# stages a production tablet moves garments to
TABLET_STATES = ["sorted", "washed", "dried", "ironed", "qc"]
# fields the board cards need (one read per refresh)
BOARD_CARD_LIMIT = 400
SCAN_SCREEN_ACTION = "earlydryer_tagging.action_earlydryer_scan_screen"


class LaundryJob(models.Model):
    _inherit = "laundry.job"

    rework_ids = fields.One2many(
        "laundry.job.item.rework", "job_id", string="QC Reworks", readonly=True
    )
    rework_item_count = fields.Integer(
        string="Reworked Items", compute="_compute_rework_item_count"
    )
    unsorted_item_count = fields.Integer(
        string="Unsorted Items",
        compute="_compute_unsorted_item_count",
        help="Garments without a colour group.",
    )

    @api.depends("item_ids.rework_count")
    def _compute_rework_item_count(self):
        for job in self:
            job.rework_item_count = len(job.item_ids.filtered("rework_count"))

    @api.depends("item_ids.colour_group", "item_ids.missing")
    def _compute_unsorted_item_count(self):
        for job in self:
            job.unsorted_item_count = len(
                job.item_ids.filtered(lambda i: not i.missing and not i.colour_group)
            )

    # ------------------------------------------------------------------
    # Rights
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_production_rights(self):
        """What the current user may do on the board and the QC screen."""
        if self.env.su:
            return dict.fromkeys(
                ("move", "qc", "manager", "batches", "breakdown", "late_stages"), True
            )
        user = self.env.user
        front_desk = user.has_group(FRONT_DESK_GROUP)
        production = user.has_group(PRODUCTION_GROUP)
        qc = user.has_group(QC_GROUP)
        manager = user.has_group(MANAGER_GROUP)
        return {
            "move": front_desk or production,
            "qc": qc,
            "manager": manager,
            "batches": production,
            "breakdown": front_desk or production,
            # Production Staff stop before packing; QC and the desk go on
            "late_stages": front_desk or qc or manager,
        }

    def _earlydryer_check_move_right(self, target_state):
        rights = self._earlydryer_production_rights()
        if not rights["move"]:
            raise AccessError(self.env._("You are not allowed to move laundry jobs."))
        if target_state in PRODUCTION_FORBIDDEN_STATES and not rights["late_stages"]:
            raise AccessError(
                self.env._(
                    "Production staff cannot move jobs to %(stage)s: the front "
                    "desk, QC or a Branch Manager does.",
                    stage=self._earlydryer_state_label(target_state),
                )
            )

    def _earlydryer_check_qc_right(self):
        if not self._earlydryer_production_rights()["qc"]:
            raise AccessError(
                self.env._("Only Quality Control can pass or fail items.")
            )

    # ------------------------------------------------------------------
    # Stage moves (earlydryer_laundry_order / earlydryer_tagging)
    # ------------------------------------------------------------------

    def action_move_to(self, target_state, employee=None, items=None, note=None):
        """Check the production rights first; the stage log ``source`` comes
        from the ``earlydryer_move_source`` context key (see
        ``laundry.job.stage.log.create``)."""
        self._earlydryer_check_move_right(target_state)
        return super().action_move_to(
            target_state, employee=employee, items=items, note=note
        )

    def _earlydryer_check_gate(self, target):
        res = super()._earlydryer_check_gate(target)
        branch = self.earlydryer_branch_id
        if target == "sorted" and branch.require_sorting_colour_group:
            unsorted = self.item_ids.filtered(
                lambda i: not i.missing and not i.colour_group
            )
            if unsorted:
                raise UserError(
                    self.env._(
                        "Sort job %(job)s first: %(count)s garment(s) without a "
                        "colour group.",
                        job=self.name,
                        count=len(unsorted),
                    )
                )
        return res

    def _earlydryer_on_state_changed(self, old_state, new_state):
        res = super()._earlydryer_on_state_changed(old_state, new_state)
        self.earlydryer_branch_id._earlydryer_board_notify(self)
        return res

    @api.model
    def earlydryer_scan_move(self, codes, target_state, employee_id, note=None):
        jobs = self
        if not self.env.context.get(SOURCE_CTX):
            jobs = self.with_context(**{SOURCE_CTX: "scan"})
        return super(LaundryJob, jobs).earlydryer_scan_move(
            codes, target_state, employee_id, note=note
        )

    def _earlydryer_clean_context(self):
        """``self`` without the default_* keys of a wizard's opening action
        (they would leak into the stage logs and reworks)."""
        return self.with_context(clean_context(self.env.context))  # pylint: disable=context-overridden

    def action_open_sort_wizard(self):
        self.ensure_one()
        return self.env["earlydryer.sort.wizard"]._earlydryer_open(self)

    # ------------------------------------------------------------------
    # QC
    # ------------------------------------------------------------------

    def action_open_qc_wizard(self):
        self.ensure_one()
        return self.env["earlydryer.qc.wizard"]._earlydryer_open(self)

    def action_qc_pass(self, items=None, employee=None):
        self._earlydryer_check_qc_right()
        res = super().action_qc_pass(items=items, employee=employee)
        self.earlydryer_branch_id._earlydryer_board_notify(self)
        return res

    def action_qc_fail(
        self,
        items,
        employee,
        return_to_state=None,
        note=None,
        reason=None,
        photo=None,
        details=None,
    ):
        """Send ``items`` back for rework, storing why.

        :param reason: ``earlydryer.rework.reason`` (record or id) for every
            item; gives the default return stage and note
        :param photo: base64 image attached to every rework
        :param details: ``{item_id: {"reason_id", "note", "photo"}}`` per
            item, overriding ``reason`` / ``note`` / ``photo``
        :returns: the ``laundry.job.item.rework`` records
        """
        self.ensure_one()
        self._earlydryer_check_qc_right()
        Reason = self.env["earlydryer.rework.reason"]
        items = self._earlydryer_coerce_items(items).filtered(
            lambda item: item.job_id == self
        )
        if isinstance(reason, int):
            reason = Reason.browse(reason)
        reason = reason or Reason
        details = {int(key): value for key, value in (details or {}).items()}
        per_item = {}
        for item in items:
            detail = details.get(item.id, {})
            item_reason = (
                Reason.browse(detail["reason_id"])
                if detail.get("reason_id")
                else reason
            )
            per_item[item] = {
                "reason": item_reason,
                "note": detail.get("note") or note or False,
                "photo": detail.get("photo") or photo or False,
            }
        if self.earlydryer_branch_id.qc_reason_required:
            unexplained = [item for item, d in per_item.items() if not d["reason"]]
            if unexplained:
                raise UserError(
                    self.env._(
                        "Choose a rework reason for %(items)s.",
                        items=", ".join(i.display_name for i in unexplained),
                    )
                )
        reasons = Reason.union(*(d["reason"] for d in per_item.values()))
        if not return_to_state:
            # the earliest stage asked for by the reasons
            wanted = reasons.mapped("default_return_state") or ["washed"]
            return_to_state = min(wanted, key=REWORK_STATES.index)
        if not (note or "").strip():
            note = "; ".join(
                part
                for part in (
                    (d["reason"].name or "") + (f": {d['note']}" if d["note"] else "")
                    for d in per_item.values()
                )
                if part
            )
        from_state = self.state
        super(LaundryJob, self.with_context(**{SOURCE_CTX: "qc"})).action_qc_fail(
            items, employee, return_to_state, note
        )
        employee = self._earlydryer_coerce_employee(employee)
        Rework = self.env["laundry.job.item.rework"]
        reworks = Rework
        for item, detail in per_item.items():
            attachment = self.env["ir.attachment"]
            if detail["photo"]:
                attachment = attachment.create(
                    {
                        "name": self.env._("QC %(item)s.jpg", item=item.display_name),
                        "datas": detail["photo"],
                        "res_model": "laundry.job.item",
                        "res_id": item.id,
                    }
                )
                item.photo_ids = [fields.Command.link(attachment.id)]
            reworks |= Rework.create(
                {
                    "item_id": item.id,
                    "reason_id": detail["reason"].id,
                    "from_state": from_state,
                    "to_state": return_to_state,
                    "employee_id": employee.id,
                    "note": detail["note"],
                    "photo_id": attachment.id,
                }
            )
        for rework in reworks.filtered("is_damage"):
            self._earlydryer_damage_alert(rework)
        return reworks

    def _earlydryer_damage_alert(self, rework):
        """Note on the job and a To Do for the branch manager, then the hook."""
        self.ensure_one()
        body = self.env._(
            "Damage found at QC on %(item)s: %(reason)s%(note)s (checked by "
            "%(employee)s).",
            item=rework.item_id.display_name,
            reason=rework.reason_id.name,
            note=f" - {rework.note}" if rework.note else "",
            employee=rework.employee_id.name or self.env.user.name,
        )
        self.message_post(
            body=body,
            subtype_xmlid="mail.mt_note",
            attachment_ids=rework.photo_id.ids,
        )
        summary = self.env._("Damage found on %(job)s", job=self.name)
        for user in self._earlydryer_request_users():
            self.sudo().activity_schedule(
                TODO_ACTIVITY, summary=summary, note=body, user_id=user.id
            )
        self._earlydryer_on_damage_found(rework)

    def _earlydryer_on_damage_found(self, rework):
        """Hook: a garment was found damaged at QC (``rework.is_damage``).
        earlydryer_claims opens a claim from here."""
        self.ensure_one()
        return

    def action_earlydryer_qc_pack(self, employee=None):
        """All passed: pack through the normal API, or open the Pack screen
        when the plant scans garments at packing."""
        self.ensure_one()
        employee = self._earlydryer_coerce_employee(employee) or (
            self._earlydryer_default_employee()
        )
        pending = self.item_ids.filtered(lambda i: i.qc_state != "passed")
        if pending:
            raise UserError(
                self.env._(
                    "%(count)s garment(s) of %(job)s have not passed QC.",
                    count=len(pending),
                    job=self.name,
                )
            )
        if (
            self.earlydryer_branch_id.tag_require_packing_scan
            and self._earlydryer_pack_expected_items().filtered(
                lambda i: not i.packed_scanned
            )
        ):
            action = self.env["ir.actions.actions"]._for_xml_id(SCAN_SCREEN_ACTION)
            action["context"] = {"earlydryer_scan_mode": "pack", "code": self.name}
            return action
        self.with_context(**{SOURCE_CTX: "qc"}).action_move_to(
            "packed", employee=employee
        )
        return True

    # ------------------------------------------------------------------
    # Stage board: data
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_board_branch(self, branch_id):
        """The board's branch: the one asked for when allowed, else the
        user's default branch."""
        user = self.env.user
        allowed = user._earlydryer_allowed_branches().filtered(
            lambda b: b.company_id in self.env.companies
        )
        if not allowed:
            raise AccessError(self.env._("You do not work on any plant."))
        branch = allowed.filtered(lambda b: b.id == branch_id)
        if not branch:
            default = user.sudo().earlydryer_branch_id
            branch = default if default in allowed else allowed[:1]
        return branch.with_env(self.env)

    @api.model
    def _earlydryer_board_states(self, branch):
        states = list(FORWARD_PATH)
        has_delivery = self.search_count(
            [
                ("earlydryer_branch_id", "=", branch.id),
                "|",
                ("state", "=", "out_for_delivery"),
                "&",
                ("fulfilment", "=", "deliver"),
                ("state", "not in", list(FINAL_STATES)),
            ],
            limit=1,
        )
        if has_delivery:
            states.append("out_for_delivery")
        return states

    @api.model
    def _earlydryer_board_domain(self, branch, states, filters=None):
        filters = filters or {}
        domain = Domain(
            [("earlydryer_branch_id", "=", branch.id), ("state", "in", states)]
        )
        if filters.get("express"):
            domain &= Domain("express", "=", True)
        if filters.get("overdue"):
            domain &= Domain("is_overdue", "=", True)
        if filters.get("due_today"):
            start, end = self._earlydryer_today_bounds()
            domain &= Domain([("promised_on", ">=", start), ("promised_on", "<", end)])
        if filters.get("channel"):
            domain &= Domain("channel", "=", filters["channel"])
        search = (filters.get("search") or "").strip()
        if search:
            domain &= Domain(
                [
                    "|",
                    "|",
                    ("name", "ilike", search),
                    ("partner_id.name", "ilike", search),
                    ("item_ids.tag_code", "ilike", search),
                ]
            )
        return domain

    @api.model
    def _earlydryer_today_bounds(self):
        """Start and end of the user's today, in UTC (naive)."""
        local_now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
        start = start.astimezone(UTC).replace(tzinfo=None)
        return start, start + timedelta(days=1)

    def _earlydryer_stage_since(self):
        """``{job_id: datetime}`` the jobs entered their current stage."""
        if not self:
            return {}
        logs = (
            self.env["laundry.job.stage.log"]
            .sudo()
            .search_read(
                [("job_id", "in", self.ids)],
                ["job_id", "to_state", "date"],
                order="date desc, id desc",
            )
        )
        since = {}
        states = {job.id: job.state for job in self}
        for log in logs:
            job_id = log["job_id"][0]
            if job_id not in since and log["to_state"] == states[job_id]:
                since[job_id] = log["date"]
        return since

    def _earlydryer_board_cards(self):
        """Plain JSON of the cards of ``self`` (one query set for all)."""
        since = self._earlydryer_stage_since()
        Batch = self.env["earlydryer.wash.batch"]
        cards = []
        for job in self:
            branch = job.earlydryer_branch_id
            progress = ""
            if branch.use_wash_batches and job.state in ("sorted", "washed"):
                batch_type = "wash" if job.state == "sorted" else "dry"
                done, total = Batch._earlydryer_job_progress(job, batch_type)
                if done and total:
                    label = job._earlydryer_state_label(BATCH_STAGES[batch_type][1])
                    progress = f"{done}/{total} {label.lower()}"
            cards.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "state": job.state,
                    "next_state": job.next_state or False,
                    "customer": job._earlydryer_customer_short_name(),
                    "item_count": job.item_count,
                    "rework": bool(job.item_ids.filtered("rework_count")),
                    "express": job.express,
                    "overdue": job.is_overdue,
                    "promised_on": fields.Datetime.to_string(job.promised_on)
                    if job.promised_on
                    else False,
                    "stage_since": fields.Datetime.to_string(since[job.id])
                    if job.id in since
                    else False,
                    "balance_due": job.is_unpaid,
                    "shelf": job.shelf_id.name or "",
                    "fulfilment": job.fulfilment,
                    "channel": job.channel,
                    "unsorted": job.unsorted_item_count,
                    "batch_progress": progress,
                }
            )
        return cards

    @api.model
    def _earlydryer_board_sort_key(self, card):
        # overdue first, then express, then promised time (none last)
        return (
            not card["overdue"],
            not card["express"],
            card["promised_on"] or "9999",
            card["id"],
        )

    @api.model
    def _earlydryer_board_employees(self, branch):
        """The plant's staff, most recent movers first."""
        Employee = self.env["hr.employee"].sudo()
        employees = Employee.search(
            [("earlydryer_branch_id", "=", branch.id)], order="name"
        )
        recent = (
            self.env["laundry.job.stage.log"]
            .sudo()
            ._read_group(
                [
                    ("earlydryer_branch_id", "=", branch.id),
                    ("employee_id", "in", employees.ids),
                    ("date", ">=", fields.Datetime.now() - timedelta(days=7)),
                ],
                ["employee_id"],
                ["date:max"],
            )
        )
        last = {employee.id: date for employee, date in recent}
        employees = employees.sorted(
            lambda e: (-(last[e.id].timestamp()) if e.id in last else 0, e.name)
        )
        return [
            {
                "id": employee.id,
                "name": employee.name,
                "job_title": employee.job_title or "",
                "avatar": f"/web/image/hr.employee.public/{employee.id}/avatar_128",
            }
            for employee in employees
        ]

    @api.model
    def _earlydryer_board_final_counts(self, branch):
        start, _end = self._earlydryer_today_bounds()
        data = self._read_group(
            [
                ("earlydryer_branch_id", "=", branch.id),
                ("state", "in", list(FINAL_STATES)),
                ("closed_on", ">=", start),
            ],
            ["state"],
            ["__count"],
        )
        counts = dict(data)
        return [
            {"state": state, "label": label, "count": counts.get(state, 0)}
            for state, label in self._fields["state"]._description_selection(self.env)
            if state in FINAL_STATES
        ]

    @api.model
    def _earlydryer_board_machines(self, branch):
        machines = self.env["maintenance.equipment"].search(
            [
                ("earlydryer_branch_id", "=", branch.id),
                ("earlydryer_machine_type", "!=", False),
            ],
            order="earlydryer_machine_type, name",
        )
        return machines._earlydryer_strip_data()

    @api.model
    def _earlydryer_board_data(self, branch_id, filters=None):
        """Everything the stage board shows, as plain JSON.

        :param branch_id: plant to show; users without
            ``group_all_branches`` only get their own plants (default branch
            when ``branch_id`` is not theirs)
        :param filters: ``{"express", "overdue", "due_today": bool,
            "channel": str, "search": str}``
        :returns: ``{"branch", "branches", "columns", "final_counts",
            "employees", "machines", "rights", ...}``; each column has
            ``cards`` sorted overdue, express, promised time
        """
        branch = self._earlydryer_board_branch(branch_id)
        states = self._earlydryer_board_states(branch)
        jobs = self.search(
            self._earlydryer_board_domain(branch, states, filters),
            limit=BOARD_CARD_LIMIT,
            order="promised_on, id",
        )
        cards = sorted(
            jobs._earlydryer_board_cards(), key=self._earlydryer_board_sort_key
        )
        labels = dict(self._fields["state"]._description_selection(self.env))
        user = self.env.user
        all_branches = user.has_group(ALL_BRANCHES_GROUP)
        allowed = user._earlydryer_allowed_branches()
        return {
            "branch": {
                "id": branch.id,
                "name": branch.display_name,
                "production_mode": branch.production_mode,
                "refresh_seconds": max(branch.board_refresh_seconds, 5),
                "tablet_idle_seconds": max(branch.tablet_idle_seconds, 10),
                "use_wash_batches": branch.use_wash_batches,
                "require_sorting_colour_group": branch.require_sorting_colour_group,
            },
            "branches": [{"id": b.id, "name": b.display_name} for b in allowed]
            if all_branches or len(allowed) > 1
            else [],
            "columns": [
                {
                    "state": state,
                    "label": labels[state],
                    "cards": [card for card in cards if card["state"] == state],
                }
                for state in states
            ],
            "truncated": len(jobs) >= BOARD_CARD_LIMIT,
            "final_counts": self._earlydryer_board_final_counts(branch),
            "employees": self._earlydryer_board_employees(branch),
            "employee_states": sorted(PRODUCTION_STATES),
            "tablet_states": [[s, labels[s]] for s in TABLET_STATES],
            "machines": self._earlydryer_board_machines(branch),
            "rights": self._earlydryer_production_rights(),
            "channels": self._fields["channel"]._description_selection(self.env),
            "default_employee_id": self._earlydryer_default_employee().id or False,
            "server_now": fields.Datetime.to_string(fields.Datetime.now()),
        }

    def _earlydryer_board_card(self, job=None):
        """Card of one job (``job`` or ``self``), or False when it left the
        board (final stage, other plant, no access)."""
        job = (job or self)[:1]
        job = self.search(
            [("id", "=", job.id), ("state", "not in", list(FINAL_STATES))]
        )
        if not job:
            return False
        return job._earlydryer_board_cards()[0]

    # ------------------------------------------------------------------
    # Stage board: RPC (public wrappers of the methods above)
    # ------------------------------------------------------------------

    @api.model
    def earlydryer_board_data(self, branch_id=False, filters=None):
        return self._earlydryer_board_data(branch_id, filters)

    @api.model
    def earlydryer_board_cards(self, job_ids, branch_id=False):
        """Refresh the cards of ``job_ids`` (after a bus notification).

        :returns: ``{"cards": [...], "removed_ids": [...], "final_counts"}``
        """
        cards, removed = [], []
        for job in self.browse(job_ids):
            card = self._earlydryer_board_card(job)
            if card:
                cards.append(card)
            else:
                removed.append(job.id)
        res = {"cards": cards, "removed_ids": removed}
        if branch_id:
            branch = self._earlydryer_board_branch(branch_id)
            res["final_counts"] = self._earlydryer_board_final_counts(branch)
            res["machines"] = self._earlydryer_board_machines(branch)
        return res

    @api.model
    def earlydryer_board_move(
        self, job_ids, target_state, employee_id=False, note=False, tablet_token=False
    ):
        """Move jobs from the board, one ``action_move_to`` per job.

        :param tablet_token: in tablet mode, the token of the identified
            employee (``earlydryer_tablet_identify``), who did the work
        :returns: ``{"results": [{"job_id", "ok", "message"}], "cards",
            "removed_ids"}``; a refused job keeps its stage
        """
        jobs = self.browse(job_ids).exists()
        source = "board"
        employee = self.env["hr.employee"].browse(employee_id or [])
        if tablet_token:
            employee = self.env[
                "earlydryer.tablet.identification"
            ]._earlydryer_check_token(tablet_token, jobs[:1].earlydryer_branch_id)
            source = "tablet"
        results = []
        for job in jobs:
            # like the form's Next Stage: the user's own employee by default,
            # never on production stages (who did the work is picked there)
            job_employee = employee
            if not employee and target_state not in PRODUCTION_STATES:
                job_employee = job._earlydryer_default_employee()
            try:
                with self.env.cr.savepoint():
                    job.with_context(**{SOURCE_CTX: source}).action_move_to(
                        target_state, employee=job_employee, note=note or None
                    )
                results.append({"job_id": job.id, "ok": True, "message": ""})
            except (UserError, AccessError, ValidationError) as error:
                results.append(
                    {
                        "job_id": job.id,
                        "ok": False,
                        "message": str(error.args[0] if error.args else error),
                    }
                )
        return {"results": results, **self.earlydryer_board_cards(jobs.ids)}

    @api.model
    def earlydryer_board_job_detail(self, job_id):
        """Side panel of a card: garments and the recent stage log."""
        job = self.browse(job_id).exists()
        job.check_access("read")
        labels = dict(self._fields["state"]._description_selection(self.env))
        sources = dict(
            self.env["laundry.job.stage.log"]
            ._fields["source"]
            ._description_selection(self.env)
        )
        groups = dict(
            self.env["laundry.job.item"]
            ._fields["colour_group"]
            ._description_selection(self.env)
        )
        qc_labels = dict(
            self.env["laundry.job.item"]
            ._fields["qc_state"]
            ._description_selection(self.env)
        )
        return {
            **job._earlydryer_board_cards()[0],
            "partner": job.partner_id.display_name,
            "state_label": labels.get(job.state),
            "customer_note": job.customer_note or "",
            "items": [
                {
                    "id": item.id,
                    "label": item.display_name,
                    "tag": item.tag_code or "",
                    "colour": item.colour or "",
                    "colour_group": groups.get(item.colour_group, ""),
                    "qc_state": item.qc_state,
                    "qc_label": qc_labels.get(item.qc_state),
                    "rework_count": item.rework_count,
                    "missing": item.missing,
                }
                for item in job.item_ids
            ],
            "logs": [
                {
                    "id": log.id,
                    "date": format_datetime(self.env, log.date, dt_format="short"),
                    "from": labels.get(log.from_state, ""),
                    "to": labels.get(log.to_state, ""),
                    "employee": log.employee_id.name or "",
                    "source": sources.get(log.source, ""),
                    "item_count": log.item_count,
                }
                for log in job.stage_log_ids[:8]
            ],
        }

    @api.model
    def earlydryer_board_open_sort(self, job_id, employee_id=False, move=True):
        job = self.browse(job_id).exists()
        return self.env["earlydryer.sort.wizard"]._earlydryer_open(
            job, employee_id=employee_id, move=move
        )

    @api.model
    def earlydryer_board_open_qc(self, job_id, employee_id=False):
        job = self.browse(job_id).exists()
        return self.env["earlydryer.qc.wizard"]._earlydryer_open(
            job, employee_id=employee_id
        )

    # ------------------------------------------------------------------
    # Production tablet: RPC
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_identity(self, employee, ident, branch):
        return {
            "ok": True,
            "employee_id": employee.id,
            "name": employee.sudo().name,
            "avatar": f"/web/image/hr.employee.public/{employee.id}/avatar_128",
            "token": ident.sudo().token,
            "idle_seconds": max(branch.tablet_idle_seconds, 10),
            "message": self.env._("Hello %(name)s", name=employee.sudo().name),
        }

    @api.model
    def earlydryer_tablet_identify(self, code, branch_id):
        """Identify the person at the tablet by badge or PIN.

        Returns ``{"ok": False, "message"}`` instead of raising, so the
        failed attempt stays logged (it counts towards the lock)."""
        branch = self._earlydryer_board_branch(branch_id)
        try:
            employee, ident = self.env["hr.employee"]._earlydryer_identify(
                code, branch.id
            )
        except UserError as error:
            return {"ok": False, "message": str(error.args[0])}
        return self._earlydryer_identity(employee, ident, branch)

    @api.model
    def earlydryer_tablet_release(self, token):
        return self.env["earlydryer.tablet.identification"]._earlydryer_release(token)

    @api.model
    def earlydryer_tablet_scan(self, code, branch_id, target_state, token=False):
        """One scan on the production tablet.

        A badge of the plant identifies its holder; any other code is a
        garment tag or job number moved to ``target_state`` with
        ``earlydryer_scan_move`` under the identified employee.

        :returns: ``{"kind": "identity"|"move"|"error", ...}``
        """
        branch = self._earlydryer_board_branch(branch_id)
        code = (code or "").strip()
        badge = (
            self.env["hr.employee"]
            .sudo()
            .search(
                [
                    ("barcode", "=", code),
                    ("earlydryer_branch_id", "in", [branch.id, False]),
                ],
                limit=1,
            )
        )
        if badge:
            identity = self.earlydryer_tablet_identify(code, branch.id)
            return {"kind": "identity" if identity["ok"] else "error", **identity}
        try:
            employee = self.env[
                "earlydryer.tablet.identification"
            ]._earlydryer_check_token(token, branch)
        except UserError as error:
            return {"kind": "error", "relogin": True, "message": str(error.args[0])}
        if target_state not in TABLET_STATES + ["packed"]:
            return {"kind": "error", "message": self.env._("Choose the stage first.")}
        results = self.with_context(**{SOURCE_CTX: "tablet"}).earlydryer_scan_move(
            [code], target_state, employee.id
        )
        job_ids = [r["job_id"] for r in results if r.get("job_id")]
        return {
            "kind": "move",
            "results": results,
            **self.earlydryer_board_cards(job_ids),
        }

    # ------------------------------------------------------------------
    # Demo data
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_load_demo_production(self):
        """Demo only: colour groups, batches in several states and QC reworks
        (one damage) on top of the demo jobs of the earlier modules."""
        ref = self.env.ref
        set_service_colour_groups(self.env)
        plant_1 = ref("earlydryer_base.branch_plant_1")
        plant_2 = ref("earlydryer_base.branch_plant_2")
        Batch = self.env["earlydryer.wash.batch"]
        jobs = self.search([("earlydryer_branch_id", "in", (plant_1 | plant_2).ids)])
        # sorting already done on the demo jobs past Tagged
        for item in jobs.item_ids.filtered(lambda i: not i.colour_group):
            if item.job_state in ("received", "tagged"):
                continue
            white = (item.colour or "").lower() == "white"
            item.colour_group = "whites" if white else "colours"

        # plant 2 (batches on): the sorted garments are in a running wash
        musa = ref("earlydryer_laundry_order.employee_washer_p2")
        sorted_jobs = jobs.filtered(
            lambda j: j.earlydryer_branch_id == plant_2 and j.state == "sorted"
        )
        if sorted_jobs:
            Batch.create(
                {
                    "earlydryer_branch_id": plant_2.id,
                    "batch_type": "wash",
                    "machine_id": ref("earlydryer_production.equipment_washer_p2_a").id,
                    "colour_group": "whites",
                    "employee_id": musa.id,
                    "program": "60 °C whites",
                    "load_weight_kg": 6.5,
                    "item_ids": [fields.Command.set(sorted_jobs.item_ids.ids)],
                }
            ).action_start()
        now = fields.Datetime.now()
        Batch.create(
            {
                "earlydryer_branch_id": plant_2.id,
                "batch_type": "dry",
                "machine_id": ref("earlydryer_production.equipment_dryer_p2_a").id,
                "employee_id": musa.id,
                "program": "Low heat",
                "note": self.env._("Demo: an earlier load."),
            }
        ).write(
            {
                "state": "done",
                "started_on": now - timedelta(hours=2),
                "finished_on": now - timedelta(hours=1),
            }
        )
        Batch.create(
            {
                "earlydryer_branch_id": plant_2.id,
                "batch_type": "wash",
                "colour_group": "darks",
                "program": "30 °C darks",
            }
        )
        # plant 2: the express gown fails QC for poor ironing
        emeka = ref("earlydryer_laundry_order.employee_qc_p2")
        for job in jobs.filtered(
            lambda j: j.earlydryer_branch_id == plant_2 and j.state == "ironed"
        ):
            job.action_move_to("qc", employee=emeka)
            job.action_qc_fail(
                job.item_ids[:1],
                emeka,
                reason=ref("earlydryer_production.rework_reason_poor_ironing"),
            )
        # plant 1: damage found on the washed suit (To Do for the manager)
        ngozi = ref("earlydryer_laundry_order.employee_qc_p1")
        washed = jobs.filtered(
            lambda j: j.earlydryer_branch_id == plant_1 and j.state == "washed"
        )[:1]
        if washed:
            for state in ("dried", "ironed", "qc"):
                washed.action_move_to(state, employee=ngozi)
            washed.action_qc_fail(
                washed.item_ids[:1],
                ngozi,
                reason=ref("earlydryer_production.rework_reason_damage"),
                note=self.env._("Small tear at the lining, not noted at intake."),
            )
        return True
