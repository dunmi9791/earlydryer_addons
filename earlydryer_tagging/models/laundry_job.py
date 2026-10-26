# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
import re
from collections import OrderedDict

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.earlydryer_laundry_order.models.laundry_job import (
    FINAL_STATES,
    FORWARD_PATH,
    STATES,
    TODO_ACTIVITY,
)

from .earlydryer_scan_log import MISMATCH_RESULTS
from .earlydryer_tag_code import normalize_code
from .laundry_job_item import CLOSED_STATES

_logger = logging.getLogger(__name__)

FRONT_DESK_GROUP = "earlydryer_base.group_front_desk"
PRODUCTION_GROUP = "earlydryer_base.group_production"
MANAGER_GROUP = "earlydryer_base.group_branch_manager"
# a job number such as P1/26/00001; tag codes never contain "/"
JOB_NUMBER_RE = re.compile(r"^[A-Z0-9]+/\d+/\d+$")
# where packing scans happen
PACKING_STATES = ("qc", "packed")
GARMENT_TAG_REPORT = "earlydryer_tagging.action_report_garment_tag"
BAG_LABEL_REPORT = "earlydryer_tagging.action_report_bag_label"


class _ZplValues(dict):
    """format_map values leaving unknown placeholders as they are."""

    def __missing__(self, key):
        return "{" + key + "}"


def _zpl_safe(value):
    # ^ and ~ start ZPL commands
    return str(value or "").replace("^", " ").replace("~", " ")


class LaundryJob(models.Model):
    _inherit = "laundry.job"

    tag_mode = fields.Selection(related="earlydryer_branch_id.tag_mode")
    tag_missing_count = fields.Integer(
        string="Untagged Items",
        compute="_compute_tag_counts",
        help="Items whose service needs a tag and that have none yet.",
    )
    pack_expected_count = fields.Integer(
        string="To Scan at Packing", compute="_compute_tag_counts"
    )
    pack_scanned_count = fields.Integer(
        string="Scanned at Packing", compute="_compute_tag_counts"
    )

    @api.depends(
        "item_ids.tag_code",
        "item_ids.tag_required",
        "item_ids.packed_scanned",
        "item_ids.missing",
    )
    def _compute_tag_counts(self):
        for job in self:
            job.tag_missing_count = len(job.item_ids._earlydryer_needs_tag())
            expected = job._earlydryer_pack_expected_items()
            job.pack_expected_count = len(expected)
            job.pack_scanned_count = len(expected.filtered("packed_scanned"))

    # ------------------------------------------------------------------
    # Rights
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_tag_rights(self):
        """What the current user may do with tags and scans."""
        user = self.env.user
        if self.env.su:
            return dict.fromkeys(
                ("assign", "print", "move", "pack", "manager", "find"), True
            )
        front_desk = user.has_group(FRONT_DESK_GROUP)
        production = user.has_group(PRODUCTION_GROUP)
        return {
            "assign": front_desk,
            "print": front_desk or production,
            "move": front_desk or production,
            "pack": front_desk or production,
            "manager": user.has_group(MANAGER_GROUP),
            "find": user._is_internal(),
        }

    @api.model
    def _earlydryer_check_tag_right(self, right):
        if not self._earlydryer_tag_rights().get(right):
            messages = {
                "assign": self.env._("Only the front desk can assign and print tags."),
                "print": self.env._("You are not allowed to print tags."),
                "move": self.env._("You are not allowed to move jobs by scanning."),
                "pack": self.env._("You are not allowed to pack jobs."),
                "manager": self.env._("Only a Branch Manager can do this."),
                "find": self.env._("You are not allowed to scan."),
            }
            raise AccessError(messages[right])

    # ------------------------------------------------------------------
    # Gates and hooks of earlydryer_laundry_order
    # ------------------------------------------------------------------

    def _check_can_tag(self):
        """Tagged only when every item whose service needs a tag has a valid one."""
        res = super()._check_can_tag()
        TagCode = self.env["earlydryer.tag.code"]
        branch = self.earlydryer_branch_id
        for item in self.item_ids.filtered("tag_required"):
            if not item.tag_code or not TagCode.is_valid_for_branch(
                item.tag_code, branch
            ):
                return False
        return res

    def _earlydryer_pack_expected_items(self):
        """Items to scan at packing: tagged ones, not flagged missing."""
        self.ensure_one()
        return self.item_ids.filtered(
            lambda item: item.tag_required and item.tag_code and not item.missing
        )

    def _earlydryer_check_gate(self, target):
        res = super()._earlydryer_check_gate(target)
        if target == "packed" and self.earlydryer_branch_id.tag_require_packing_scan:
            unscanned = self._earlydryer_pack_expected_items().filtered(
                lambda item: not item.packed_scanned
            )
            if unscanned:
                raise UserError(
                    self.env._(
                        "Scan every garment of job %(job)s before packing: "
                        "%(count)s not scanned (%(items)s).",
                        job=self.name,
                        count=len(unscanned),
                        items=", ".join(unscanned.mapped("tag_code")),
                    )
                )
        return res

    def _earlydryer_on_state_changed(self, old_state, new_state):
        res = super()._earlydryer_on_state_changed(old_state, new_state)
        if (
            old_state in FORWARD_PATH
            and new_state in FORWARD_PATH
            and FORWARD_PATH.index(new_state) < FORWARD_PATH.index(old_state)
        ):
            # sent back (QC rework, correction): pack again from scratch
            self.item_ids.filtered("packed_scanned").sudo().write(
                {"packed_scanned": False, "packed_scanned_on": False}
            )
        return res

    # ------------------------------------------------------------------
    # Assigning and printing
    # ------------------------------------------------------------------

    def _earlydryer_customer_short_name(self):
        """First name and initial (never the phone): "Adaeze O."."""
        self.ensure_one()
        partner = self.partner_id.sudo()
        name = (partner.name or "").strip()
        if partner.is_company or not name:
            return name[:20]
        parts = name.split()
        if len(parts) == 1:
            return parts[0][:20]
        return f"{parts[0][:16]} {parts[-1][0].upper()}."

    def _earlydryer_tag_after_assign(self):
        """Received jobs whose items are now all tagged move to Tagged."""
        for job in self.filtered(lambda j: j.state == "received"):
            if job._check_can_tag():
                job.action_move_to(
                    "tagged", employee=job._earlydryer_default_employee()
                )

    def action_assign_tags(self):
        """Give a tag to every item needing one.

        Printed plants: codes from the plant's sequence, then the jobs move to
        Tagged. Pre-printed plants: a wizard to scan each physical tag in turn.
        """
        self._earlydryer_check_tag_right("assign")
        jobs = self.filtered(lambda j: j.state not in CLOSED_STATES)
        preprinted = jobs.filtered(
            lambda j: j.tag_mode == "preprinted" and j.item_ids._earlydryer_needs_tag()
        )
        printed = jobs - preprinted
        printed.item_ids.sudo()._earlydryer_assign_generated_codes()
        printed._earlydryer_tag_after_assign()
        if preprinted:
            return self.env["earlydryer.tag.assign.wizard"]._earlydryer_open(preprinted)
        return True

    def action_assign_and_print_tags(self):
        """Header button: assign the missing codes, then print the tags."""
        action = self.action_assign_tags()
        if isinstance(action, dict):
            return action
        return self._earlydryer_print_tags(self.item_ids)

    def action_print_tags(self):
        """Batch print from the job list (assigns missing printed codes first
        when the user is allowed to)."""
        if self._earlydryer_tag_rights()["assign"]:
            printed = self.filtered(
                lambda j: j.tag_mode == "printed" and j.state not in CLOSED_STATES
            )
            printed.item_ids.sudo()._earlydryer_assign_generated_codes()
            printed._earlydryer_tag_after_assign()
        return self._earlydryer_print_tags(self.item_ids)

    def action_reprint_tags(self):
        return self._earlydryer_print_tags(self.item_ids)

    def _earlydryer_print_tags(self, items):
        """Report action of the tags of ``items``; reprints are logged."""
        self._earlydryer_check_tag_right("print")
        items = items.filtered("tag_code")
        if not items:
            raise UserError(self.env._("No garment has a tag to print yet."))
        for job in items.job_id:
            reprinted = items.filtered(
                lambda item, job=job: item.job_id == job and item.tag_print_count
            )
            if reprinted:
                job.message_post(
                    body=self.env._(
                        "Tags reprinted by %(user)s: %(count)s label(s) (%(codes)s).",
                        user=self.env.user.name,
                        count=len(reprinted),
                        codes=", ".join(reprinted.mapped("tag_code")),
                    ),
                    subtype_xmlid="mail.mt_note",
                )
        for item in items.sudo():
            item.tag_print_count += 1
        return self.env.ref(GARMENT_TAG_REPORT).report_action(items)

    def action_print_bag_label(self):
        self._earlydryer_check_tag_right("print")
        return self.env.ref(BAG_LABEL_REPORT).report_action(self)

    def _earlydryer_zpl(self):
        """ZPL text of the tags of the jobs (one label per tagged item)."""
        labels = []
        for item in self.item_ids.filtered("tag_code"):
            template = item.earlydryer_branch_id.tag_zpl_template or ""
            values = _ZplValues(
                {
                    key: _zpl_safe(value)
                    for key, value in item._earlydryer_label_values().items()
                }
            )
            labels.append(template.format_map(values).strip())
        return "\n".join(labels) + "\n"

    def action_download_zpl(self):
        """Raw labels for Zebra-compatible printers set up to receive files."""
        self._earlydryer_check_tag_right("print")
        if not self.item_ids.filtered("tag_code"):
            raise UserError(self.env._("No garment has a tag to print yet."))
        name = (self[:1].name or "tags").replace("/", "-")
        if len(self) > 1:
            name = self.env._("tags-%(count)s-jobs", count=len(self))
        attachment = (
            self.env["ir.attachment"]
            .sudo()
            .create(
                {
                    "name": f"{name}.zpl",
                    "raw": self._earlydryer_zpl().encode(),
                    "mimetype": "text/plain",
                    "res_model": self._name,
                    "res_id": self[:1].id,
                }
            )
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    # ------------------------------------------------------------------
    # Scan API (scan screen, production board, POS)
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_scan_log(self, code, mode, result, job=None, item=None, **extra):
        job = job or self.browse()
        branch = job.earlydryer_branch_id or extra.pop("branch", None)
        extra.pop("branch", None)
        if not branch:
            branch = self.env.user.sudo().earlydryer_branch_id
        return (
            self.env["earlydryer.scan.log"]
            .sudo()
            .create(
                {
                    "code": code or "?",
                    "mode": mode,
                    "result": result,
                    "job_id": job.id,
                    "item_id": item.id if item else False,
                    "earlydryer_branch_id": branch.id if branch else False,
                    "user_id": self.env.uid,
                    **extra,
                }
            )
        )

    @api.model
    def _earlydryer_find_item(self, code, branch=None, sudo=False):
        """Item carrying ``code`` (open jobs first: pre-printed tags are reused)."""
        Item = self.env["laundry.job.item"]
        if sudo:
            Item = Item.sudo()
        items = Item.search([("tag_code", "=", code)], order="id desc")
        if not items:
            return Item
        items = items.sorted(
            lambda item: (
                item.job_state not in CLOSED_STATES,
                bool(branch) and item.earlydryer_branch_id == branch,
                item.id,
            ),
            reverse=True,
        )
        return items[:1]

    @api.model
    def _earlydryer_resolve(self, code, branch=None):
        """``(kind, job, item)`` for ``code``: kind is item, job, invalid or
        unknown. Only what the user may see is found."""
        if not code:
            return "unknown", self.browse(), self.env["laundry.job.item"]
        if JOB_NUMBER_RE.match(code):
            job = self.search([("name", "=", code)], limit=1)
            return ("job" if job else "unknown"), job, self.env["laundry.job.item"]
        info = self.env["earlydryer.tag.code"].parse(code)
        if info and not info["valid"]:
            return "invalid", self.browse(), self.env["laundry.job.item"]
        item = self._earlydryer_find_item(code, branch)
        if item:
            return "item", item.job_id, item
        return "unknown", self.browse(), item

    def _earlydryer_scan_card(self):
        """What a scan shows of the job."""
        self.ensure_one()
        return {
            "job_id": self.id,
            "job_name": self.name,
            "state": self.state,
            "state_label": self._earlydryer_state_label(self.state),
            "customer": self.partner_id.display_name,
            "branch_id": self.earlydryer_branch_id.id,
            "branch_name": self.earlydryer_branch_id.display_name,
            "shelf": self.shelf_id.display_name or "",
            "express": self.express,
            "item_count": self.item_count,
            "amount_due": self.amount_due,
            "amount_due_display": self._earlydryer_format_amount(self.amount_due),
            "promised_on": fields.Datetime.to_string(self.promised_on)
            if self.promised_on
            else False,
        }

    @api.model
    def _earlydryer_unknown_message(self, code):
        replaced = self.env["earlydryer.tag.history"].search(
            [("old_code", "=", code)], limit=1
        )
        if replaced:
            return self.env._(
                "Tag %(code)s was replaced by %(new)s (job %(job)s).",
                code=code,
                new=replaced.new_code or "-",
                job=replaced.job_id.name,
            )
        return self.env._("No garment or job found for %(code)s.", code=code)

    @api.model
    def earlydryer_scan_lookup(self, code, branch_id=None, log=True):
        """Find the job of a garment tag or job number.

        :param code: scanned or typed tag code or job number
        :param branch_id: plant of the scanning screen (preferred on reuse)
        :param log: False for a preview (the scan screen checks the codes of
            a batch move before committing it; the move logs them)
        :returns: ``{"type": "item"|"job"|"unknown"|"invalid", "job_id",
            "item_id", "job_name", "state", "customer", "branch_id",
            "message", ...}``. Codes of plants the user cannot see are
            ``unknown``, like codes nobody uses.
        """
        self._earlydryer_check_tag_right("find")
        code = normalize_code(code)
        branch = self.env["earlydryer.branch"].browse(branch_id or [])
        kind, job, item = self._earlydryer_resolve(code, branch)
        res = {
            "type": kind,
            "code": code,
            "job_id": False,
            "item_id": False,
            "job_name": False,
            "state": False,
            "customer": False,
            "branch_id": False,
            "message": "",
        }
        if kind == "invalid":
            res["message"] = self.env._(
                "%(code)s is not a valid tag code: check digit wrong. Scan again "
                "or type it carefully.",
                code=code,
            )
        elif kind == "unknown":
            res["message"] = self._earlydryer_unknown_message(code)
        else:
            res.update(job._earlydryer_scan_card())
            res["item_id"] = item.id
            if item:
                res["item_label"] = item.display_name
                res["message"] = self.env._(
                    "%(item)s of job %(job)s", item=item.display_name, job=job.name
                )
            else:
                res["message"] = self.env._("Job %(job)s", job=job.name)
        if not log:
            return res
        self._earlydryer_scan_log(
            code,
            "find",
            "ok" if kind in ("item", "job") else kind,
            job=job,
            item=item,
            branch=branch,
            message=res["message"][:255],
        )
        return res

    @api.model
    def earlydryer_scan_move(self, codes, target_state, employee_id, note=None):
        """Move the jobs of the scanned garments (or job numbers) to a stage.

        Items are grouped by job and ``action_move_to`` is called once per
        job with the scanned items, so the stage log says which garments were
        scanned. Moving one garment moves its whole job.

        :returns: list of ``{"code", "result", "type", "job_id", "job_name",
            "item_id", "message", "warning"}``, one per code
        """
        self._earlydryer_check_tag_right("move")
        if target_state not in dict(STATES):
            raise UserError(self.env._("Unknown stage %(stage)s.", stage=target_state))
        employee = self.env["hr.employee"].browse(employee_id or [])
        results = OrderedDict()
        groups = OrderedDict()
        for raw in codes or []:
            code = normalize_code(raw)
            if not code or code in results:
                continue
            kind, job, item = self._earlydryer_resolve(code)
            entry = {
                "code": code,
                "type": kind,
                "result": kind if kind in ("invalid", "unknown") else "ok",
                "job_id": job.id or False,
                "job_name": job.name or False,
                "item_id": item.id or False,
                "message": "",
                "warning": "",
                "_job": job,
                "_item": item,
            }
            if kind == "invalid":
                entry["message"] = self.env._("Invalid code (check digit).")
            elif kind == "unknown":
                entry["message"] = self._earlydryer_unknown_message(code)
            else:
                group = groups.setdefault(job, {"items": item.browse(), "whole": False})
                if item:
                    group["items"] |= item
                else:
                    group["whole"] = True
            results[code] = entry
        label = self._earlydryer_state_label(target_state)
        outcome = {}
        for job, group in groups.items():
            items = self.env["laundry.job.item"] if group["whole"] else group["items"]
            if job.state == target_state:
                outcome[job] = (
                    "duplicate",
                    self.env._("Already %(stage)s.", stage=label),
                )
                continue
            try:
                with self.env.cr.savepoint():
                    job.action_move_to(
                        target_state, employee=employee, items=items, note=note
                    )
            except (UserError, AccessError, ValidationError) as error:
                outcome[job] = ("refused", str(error.args[0] if error.args else error))
                continue
            warning = ""
            if not group["whole"]:
                expected = job.item_ids.filtered(
                    lambda i: i.tag_required and not i.missing
                )
                unscanned = expected - group["items"]
                if unscanned:
                    warning = self.env._(
                        "Job %(job)s: %(scanned)s of %(total)s garments scanned "
                        "(not scanned: %(codes)s).",
                        job=job.name,
                        scanned=len(expected) - len(unscanned),
                        total=len(expected),
                        codes=", ".join(
                            code for code in unscanned.mapped("tag_code") if code
                        )
                        or "-",
                    )
            outcome[job] = (
                "ok",
                self.env._(
                    "Job %(job)s moved to %(stage)s.", job=job.name, stage=label
                ),
                warning,
            )
        response = []
        for entry in results.values():
            job, item = entry.pop("_job"), entry.pop("_item")
            if job in outcome:
                result = outcome[job]
                entry["result"] = result[0]
                entry["message"] = result[1]
                entry["warning"] = result[2] if len(result) > 2 else ""
            self._earlydryer_scan_log(
                entry["code"],
                "move",
                entry["result"],
                job=job,
                item=item,
                employee_id=employee.id,
                message=(entry["message"] or "")[:255],
            )
            response.append(entry)
        return response

    def _earlydryer_pack_status(self):
        self.ensure_one()
        expected = self._earlydryer_pack_expected_items()
        unscanned = expected.filtered(lambda item: not item.packed_scanned)
        return {
            **self._earlydryer_scan_card(),
            "scanned": len(expected) - len(unscanned),
            "expected": len(expected),
            "complete": not unscanned,
            "require_scan": self.earlydryer_branch_id.tag_require_packing_scan,
            "missing_items": [
                {"id": item.id, "code": item.tag_code, "label": item.display_name}
                for item in unscanned
            ],
            "untagged_count": len(self.item_ids._earlydryer_needs_tag()),
        }

    def _earlydryer_check_packable(self):
        self.ensure_one()
        if self.state not in PACKING_STATES:
            raise UserError(
                self.env._(
                    "Job %(job)s is %(stage)s: it is packed after QC.",
                    job=self.name,
                    stage=self._earlydryer_state_label(self.state),
                )
            )

    @api.model
    def earlydryer_pack_start(self, code):
        """Pack screen: the job of a bag label, job number or garment tag."""
        self._earlydryer_check_tag_right("pack")
        code = normalize_code(code)
        kind, job, item = self._earlydryer_resolve(code)
        if kind not in ("item", "job"):
            self._earlydryer_scan_log(code, "pack", kind)
            message = (
                self.env._("Invalid code (check digit).")
                if kind == "invalid"
                else self._earlydryer_unknown_message(code)
            )
            return {"result": kind, "message": message}
        self._earlydryer_scan_log(code, "pack", "ok", job=job, item=item)
        job._earlydryer_check_packable()
        return {"result": "ok", **job._earlydryer_pack_status()}

    @api.model
    def earlydryer_scan_pack(self, job_id, code, employee_id=None):
        """Check one garment going into the bag of job ``job_id``.

        :returns: ``{"result": "ok"|"duplicate"|"wrong_job"|"wrong_branch"|
            "unknown"|"invalid", "message", "other_job_name", "bag", ...}``
            plus the packing progress of the job. ``wrong_job`` and
            ``wrong_branch`` also post a note on both jobs and schedule an
            activity for the branch manager (``_earlydryer_on_scan_mismatch``).
            Scanning another job's bag label returns ``wrong_job`` with
            ``bag`` true and raises no alert.
        """
        self._earlydryer_check_tag_right("pack")
        job = self.browse(job_id).exists()
        job.check_access("read")
        job._earlydryer_check_packable()
        code = normalize_code(code)
        employee = self.env["hr.employee"].browse(employee_id or [])
        res = {"code": code, "bag": False, "other_job_name": False, "item_id": False}

        def done(result, message, item=None, other_job=None, log_mode="pack"):
            log = self._earlydryer_scan_log(
                code,
                log_mode,
                result,
                job=other_job or job,
                item=item,
                expected_job_id=job.id,
                employee_id=employee.id,
                message=message[:255],
            )
            if log_mode == "pack" and result in MISMATCH_RESULTS:
                job._earlydryer_on_scan_mismatch(log)
            res.update(job._earlydryer_pack_status())
            res.update(
                result=result, message=message, item_id=item.id if item else False
            )
            return res

        if JOB_NUMBER_RE.match(code):
            res["bag"] = True
            if code == job.name:
                return done("ok", self.env._("Bag label of %(job)s.", job=job.name))
            other = self.search([("name", "=", code)], limit=1)
            if not other:
                return done("unknown", self._earlydryer_unknown_message(code))
            res["other_job_name"] = other.name
            res["other_job_id"] = other.id
            return done(
                "wrong_job",
                self.env._("Bag label of another job: %(job)s.", job=other.name),
                other_job=other,
                log_mode="find",
            )
        info = self.env["earlydryer.tag.code"].parse(code)
        if info and not info["valid"]:
            return done(
                "invalid", self.env._("Invalid code (check digit): scan again.")
            )
        item = self._earlydryer_find_item(code, job.earlydryer_branch_id, sudo=True)
        if item.job_id != job:
            # prefer this job's garment when a pre-printed code is on two jobs
            own = job.item_ids.filtered(lambda i: i.tag_code == code)
            item = own[:1] or item
        if not item:
            return done("unknown", self._earlydryer_unknown_message(code))
        if item.earlydryer_branch_id != job.earlydryer_branch_id:
            visible = self.search_count([("id", "=", item.job_id.id)])
            if visible:
                res["other_job_name"] = item.job_id.name
            return done(
                "wrong_branch",
                self.env._(
                    "STOP: this garment belongs to another plant%(job)s, not to "
                    "%(expected)s.",
                    job=f" ({item.job_id.name})" if visible else "",
                    expected=job.name,
                ),
                item=item,
                other_job=item.job_id if visible else None,
            )
        if item.job_id != job:
            res["other_job_name"] = item.job_id.name
            res["other_job_id"] = item.job_id.id
            return done(
                "wrong_job",
                self.env._(
                    "STOP: this garment belongs to job %(other)s, not to %(job)s.",
                    other=item.job_id.name,
                    job=job.name,
                ),
                item=item,
                other_job=item.job_id,
            )
        item = item.with_env(self.env)
        if item.packed_scanned:
            return done(
                "duplicate",
                self.env._("%(item)s already scanned.", item=item.display_name),
                item=item,
            )
        vals = {"packed_scanned": True, "packed_scanned_on": fields.Datetime.now()}
        if item.missing:
            vals["missing"] = False
        item.write(vals)
        return done("ok", item.display_name, item=item)

    @api.model
    def earlydryer_pack_finish(
        self, job_id, employee_id, note=None, mark_missing=False
    ):
        """Finish packing: move to Packed when every garment was scanned.

        With ``mark_missing`` a Branch Manager flags the garments not scanned
        as missing (``note`` required). laundry_order does not pack a job with
        missing items, so the job then waits for the claim.
        """
        self._earlydryer_check_tag_right("pack")
        job = self.browse(job_id).exists()
        job.check_access("read")
        job._earlydryer_check_packable()
        status = job._earlydryer_pack_status()
        unscanned = self.env["laundry.job.item"].browse(
            [item["id"] for item in status["missing_items"]]
        )
        if mark_missing:
            self._earlydryer_check_tag_right("manager")
            if not (note or "").strip():
                raise UserError(self.env._("Explain why the garments are missing."))
            if not unscanned:
                raise UserError(self.env._("Every garment was scanned."))
            unscanned.write({"missing": True})
            job.message_post(
                body=Markup("%s<br/>%s")
                % (
                    self.env._(
                        "Not found at packing, flagged missing by %(user)s: %(codes)s",
                        user=self.env.user.name,
                        codes=", ".join(unscanned.mapped("tag_code")),
                    ),
                    note,
                ),
                subtype_xmlid="mail.mt_note",
            )
            return {
                "result": "missing_marked",
                "message": self.env._(
                    "%(count)s garment(s) flagged missing. Job %(job)s cannot be "
                    "packed until they are found or the claim is settled.",
                    count=len(unscanned),
                    job=job.name,
                ),
                **job._earlydryer_pack_status(),
            }
        scanned = job._earlydryer_pack_expected_items().filtered("packed_scanned")
        job.action_move_to("packed", employee=employee_id, items=scanned, note=note)
        return {
            "result": "ok",
            "message": self.env._("Job %(job)s packed.", job=job.name),
            **job._earlydryer_pack_status(),
        }

    def _earlydryer_on_scan_mismatch(self, log):
        """Hook: a garment of another job or plant was scanned while packing
        this job. Notes on both jobs, To Do for the branch manager.
        earlydryer_notifications adds a WhatsApp alert."""
        self.ensure_one()
        job = self.sudo()
        other = log.sudo().job_id
        result = dict(log._fields["result"]._description_selection(self.env)).get(
            log.result, log.result
        )
        body = self.env._(
            "Packing mismatch (%(result)s): garment %(code)s scanned by %(user)s "
            "while packing %(job)s.",
            result=result,
            code=log.code,
            user=log.sudo().user_id.name or self.env.user.name,
            job=job.name,
        )
        job.message_post(body=body, subtype_xmlid="mail.mt_note")
        if other and other != job:
            other.message_post(body=body, subtype_xmlid="mail.mt_note")
        summary = self.env._("Packing mismatch on %(job)s", job=job.name)
        for user in job._earlydryer_request_users():
            job.activity_schedule(
                TODO_ACTIVITY, summary=summary, note=body, user_id=user.id
            )
        return True

    @api.model
    def earlydryer_scan_context(self):
        """Everything the scan screen needs in one call."""
        self._earlydryer_check_tag_right("find")
        user = self.env.user.sudo()
        branches = user.earlydryer_branch_ids
        if user.has_group("earlydryer_base.group_all_branches"):
            branches = (
                self.env["earlydryer.branch"]
                .sudo()
                .search([("company_id", "in", self.env.companies.ids)])
            )
        employees = (
            self.env["hr.employee"]
            .sudo()
            .search([("earlydryer_branch_id", "in", branches.ids)], order="name")
        )
        default_employee = self._earlydryer_default_employee()
        return {
            "rights": self._earlydryer_tag_rights(),
            "branches": [
                {
                    "id": branch.id,
                    "name": branch.display_name,
                    "commit_per_scan": branch.tag_move_commit_per_scan,
                    "require_packing_scan": branch.tag_require_packing_scan,
                }
                for branch in branches
            ],
            "default_branch_id": user.earlydryer_branch_id.id or branches[:1].id,
            "employees": [
                {
                    "id": employee.id,
                    "name": employee.name,
                    "branch_id": employee.earlydryer_branch_id.id,
                }
                for employee in employees
            ],
            "default_employee_id": default_employee.id or False,
            "stages": [
                [value, label]
                for value, label in self._fields["state"]._description_selection(
                    self.env
                )
                if value not in ("received", *FINAL_STATES)
            ]
            + [
                [value, label]
                for value, label in self._fields["state"]._description_selection(
                    self.env
                )
                if value in ("collected", "delivered")
            ],
        }

    # ------------------------------------------------------------------
    # Demo data
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_load_demo_tags(self):
        """Demo only: tags on the demo jobs (plant 1 printed, plant 2
        pre-printed), a tag range for the demo till and a few scans,
        including a packing mismatch."""
        ref = self.env.ref
        plant_1 = ref("earlydryer_base.branch_plant_1")
        plant_2 = ref("earlydryer_base.branch_plant_2")
        plant_2.tag_mode = "preprinted"
        jobs_1 = self.search([("earlydryer_branch_id", "=", plant_1.id)], order="id")
        jobs_2 = self.search([("earlydryer_branch_id", "=", plant_2.id)], order="id")
        jobs_1.item_ids._earlydryer_assign_generated_codes()
        number = 1
        for item in jobs_2.item_ids._earlydryer_needs_tag():
            item.tag_code = f"ED2{number:05d}"
            number += 1
        # jobs already packed were packed before scanning existed
        packed = (jobs_1 | jobs_2).filtered(
            lambda job: job.state in ("packed", "ready", "collected", "delivered")
        )
        packed.item_ids.filtered("tag_code").write(
            {"packed_scanned": True, "packed_scanned_on": fields.Datetime.now()}
        )
        config = ref(
            "earlydryer_service_catalog.pos_config_counter_p1", raise_if_not_found=False
        )
        if config:
            self.env["earlydryer.tag.range"]._earlydryer_allocate_range(plant_1, config)
        # scans
        front_desk = ref("earlydryer_base.user_front_desk_p1")
        employee = ref("earlydryer_laundry_order.employee_front_desk_p1")
        tagged = jobs_1.filtered(lambda job: job.item_ids.filtered("tag_code"))
        if len(tagged) < 2:
            return True
        found, other = tagged[0], tagged[-1]
        as_desk = self.with_user(front_desk)
        as_desk.earlydryer_scan_lookup(found.item_ids[:1].tag_code)
        as_desk.earlydryer_scan_lookup(found.name)
        code = found.item_ids[:1].tag_code
        # a misread digit: rejected by the check digit
        as_desk.earlydryer_scan_lookup(code[:-1] + str((int(code[-1]) + 1) % 10))
        # packing ``found``: a garment of ``other`` goes into its bag
        log = self._earlydryer_scan_log(
            other.item_ids[:1].tag_code,
            "pack",
            "wrong_job",
            job=other,
            item=other.item_ids[:1],
            expected_job_id=found.id,
            employee_id=employee.id,
            user_id=front_desk.id,
            message=self.env._(
                "STOP: this garment belongs to job %(other)s, not to %(job)s.",
                other=other.name,
                job=found.name,
            ),
        )
        found._earlydryer_on_scan_mismatch(log)
        return True
