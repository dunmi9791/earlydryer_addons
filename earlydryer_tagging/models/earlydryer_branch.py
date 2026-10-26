# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import re

from odoo import api, fields, models, tools
from odoo.exceptions import UserError, ValidationError

from .earlydryer_tag_code import DEFAULT_PREPRINTED_PATTERN, MAX_NUMBER

PREFIX_RE = re.compile(r"^[A-Z0-9]+$")
# fields read by the cached prefix map
PREFIX_MAP_FIELDS = {"tag_prefix", "tag_mode", "tag_check_digit"}

DEFAULT_ZPL_TEMPLATE = """^XA
^CI28
^PW400
^LL200
^FO16,12^A0N,24,24^FD{job}  {piece}  {express}^FS
^FO16,40^BY2^BCN,80,N,N,N^FD{code}^FS
^FO16,126^A0N,30,30^FD{code}^FS
^FO16,162^A0N,24,24^FD{garment} {service}  {customer}^FS
^XZ
"""


class EarlydryerBranch(models.Model):
    _inherit = "earlydryer.branch"

    tag_mode = fields.Selection(
        [("printed", "Printed Tags"), ("preprinted", "Pre-printed Reusable Tags")],
        required=True,
        default="printed",
        tracking=True,
        help="Printed: Odoo numbers the tags and prints them (thermal or "
        "heat-seal labels). Pre-printed: numbered tags bought in rolls are "
        "attached and their number scanned at intake; they are reused once "
        "the order is closed.",
    )
    tag_prefix = fields.Char(
        tracking=True,
        copy=False,
        help="Start of every printed tag code of this plant (upper-case letters "
        "and digits). Defaults to the plant code.",
    )
    tag_sequence_id = fields.Many2one(
        "ir.sequence",
        readonly=True,
        copy=False,
        help="Numbers of the printed tags of this plant. Tag ranges for the "
        "offline POS are taken from it in blocks.",
    )
    tag_check_digit = fields.Boolean(
        string="Check Digit",
        default=True,
        help="Printed codes end with a mod-10 (Luhn) check digit, so a "
        "mistyped or misread code is rejected before any lookup. Change it "
        "only before the first tag is printed.",
    )
    tag_preprinted_pattern = fields.Char(
        string="Pre-printed Tag Pattern",
        default=DEFAULT_PREPRINTED_PATTERN,
        help="Regular expression every pre-printed tag code must match.",
    )
    tag_auto_assign = fields.Boolean(
        string="Assign Tags at Intake",
        default=True,
        help="Printed mode: give a tag code to every item that needs one as "
        "soon as the job is created (confirm, print, attach).",
    )
    tag_require_packing_scan = fields.Boolean(
        string="Scan Every Item at Packing",
        default=True,
        help="A job can only be packed once every item (not flagged missing) "
        "has been scanned on the packing screen.",
    )
    tag_move_commit_per_scan = fields.Boolean(
        string="Move on Each Scan",
        help="Scan screen, Move mode: move each job as soon as one of its "
        "garments is scanned, instead of when Done is pressed.",
    )
    tag_label_paperformat_id = fields.Many2one(
        "report.paperformat",
        string="Garment Tag Format",
        default=lambda self: self.env.ref(
            "earlydryer_tagging.paperformat_tag_thermal_50x25",
            raise_if_not_found=False,
        ),
        help="Label size of the garment tags printed for this plant.",
    )
    bag_label_paperformat_id = fields.Many2one(
        "report.paperformat",
        string="Bag Label Format",
        default=lambda self: self.env.ref(
            "earlydryer_tagging.paperformat_bag_thermal_100x50",
            raise_if_not_found=False,
        ),
        help="Label size of the bag / order labels printed for this plant.",
    )
    tag_zpl_template = fields.Text(
        string="ZPL Template",
        default=DEFAULT_ZPL_TEMPLATE,
        help="Raw label for Zebra-compatible printers set up to receive files. "
        "Placeholders: {code} {job} {garment} {service} {piece} {customer} "
        "{promised} {express} {branch}. The PDF labels are the default.",
    )
    tag_range_ids = fields.One2many(
        "earlydryer.tag.range", "branch_id", string="Tag Ranges"
    )
    tag_range_count = fields.Integer(compute="_compute_tag_range_count")

    _tag_prefix_uniq = models.Constraint(
        "unique(tag_prefix)", "The tag prefix must be unique across plants."
    )

    def _compute_tag_range_count(self):
        data = self.env["earlydryer.tag.range"]._read_group(
            [("branch_id", "in", self.ids), ("state", "=", "active")],
            ["branch_id"],
            ["__count"],
        )
        counts = {branch.id: count for branch, count in data}
        for branch in self:
            branch.tag_range_count = counts.get(branch.id, 0)

    @api.constrains("tag_prefix")
    def _check_tag_prefix(self):
        for branch in self:
            if branch.tag_prefix and not PREFIX_RE.match(branch.tag_prefix):
                raise ValidationError(
                    self.env._(
                        "The tag prefix of %(branch)s may only contain upper-case "
                        "letters and digits.",
                        branch=branch.display_name,
                    )
                )

    @api.constrains("tag_preprinted_pattern")
    def _check_tag_preprinted_pattern(self):
        for branch in self.filtered("tag_preprinted_pattern"):
            try:
                re.compile(branch.tag_preprinted_pattern)
            except re.error as error:
                raise ValidationError(
                    self.env._(
                        "Invalid pre-printed tag pattern for %(branch)s: %(error)s",
                        branch=branch.display_name,
                        error=error,
                    )
                ) from error

    @api.model
    def _normalize_vals(self, vals):
        vals = super()._normalize_vals(vals)
        if vals.get("tag_prefix"):
            vals["tag_prefix"] = vals["tag_prefix"].strip().upper()
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        branches = super().create(vals_list)
        branches._earlydryer_tag_ensure_setup()
        self.env.registry.clear_cache()
        return branches

    def write(self, vals):
        if "tag_prefix" in vals and not vals["tag_prefix"]:
            raise UserError(self.env._("A plant needs a tag prefix."))
        res = super().write(vals)
        if PREFIX_MAP_FIELDS & set(vals):
            self.env.registry.clear_cache()
        return res

    def _earlydryer_tag_ensure_setup(self):
        """Prefix (the plant code), label sizes and tag sequence of the plants
        without."""
        Sequence = self.env["ir.sequence"].sudo()
        tag_format = self.env.ref(
            "earlydryer_tagging.paperformat_tag_thermal_50x25", raise_if_not_found=False
        )
        bag_format = self.env.ref(
            "earlydryer_tagging.paperformat_bag_thermal_100x50",
            raise_if_not_found=False,
        )
        for branch in self.sudo():
            if not branch.tag_prefix:
                branch.tag_prefix = branch.code
            if not branch.tag_label_paperformat_id and tag_format:
                branch.tag_label_paperformat_id = tag_format
            if not branch.bag_label_paperformat_id and bag_format:
                branch.bag_label_paperformat_id = bag_format
            if not branch.tag_sequence_id:
                branch.tag_sequence_id = Sequence.create(
                    {
                        "name": self.env._(
                            "Garment Tags %(branch)s", branch=branch.display_name
                        ),
                        "code": f"earlydryer.tag.{branch.id}",
                        "implementation": "no_gap",
                        "padding": 7,
                        "number_next": 1,
                        "number_increment": 1,
                        "company_id": branch.company_id.id,
                    }
                )
        return True

    @api.model
    @tools.ormcache()
    def _earlydryer_tag_prefix_map(self):
        """``{prefix: (branch_id, tag_mode, check_digit)}`` of every plant."""
        branches = (
            self.sudo()
            .with_context(active_test=False)
            .search([("tag_prefix", "!=", False)])
        )
        return {
            branch.tag_prefix: (branch.id, branch.tag_mode, branch.tag_check_digit)
            for branch in branches
            if branch.tag_prefix
        }

    def _earlydryer_tag_take_numbers(self, count=1):
        """Reserve ``count`` consecutive numbers of the tag sequence.

        The sequence row is locked (no gap), so tags assigned at the counter
        and the blocks given to the offline tills never overlap. Returns the
        first number.
        """
        self.ensure_one()
        if count < 1:
            raise UserError(self.env._("At least one tag number is needed."))
        if not self.tag_sequence_id:
            self._earlydryer_tag_ensure_setup()
        sequence = self.sudo().tag_sequence_id
        self.env.cr.execute(
            "SELECT number_next, number_increment FROM ir_sequence "
            "WHERE id = %s FOR UPDATE",
            [sequence.id],
        )
        first, increment = self.env.cr.fetchone()
        if increment != 1:
            raise UserError(
                self.env._(
                    "The tag sequence of %(branch)s must increase by 1.",
                    branch=self.display_name,
                )
            )
        last = first + count - 1
        if last > MAX_NUMBER:
            raise UserError(
                self.env._(
                    "Plant %(branch)s has used all its tag numbers: give it a "
                    "new tag prefix.",
                    branch=self.display_name,
                )
            )
        self.env.cr.execute(
            "UPDATE ir_sequence SET number_next = %s WHERE id = %s",
            [last + 1, sequence.id],
        )
        sequence.invalidate_recordset(["number_next", "number_next_actual"])
        return first

    def _earlydryer_tag_next_number(self):
        """Next number the sequence would give (nothing reserved)."""
        self.ensure_one()
        return self.sudo().tag_sequence_id.number_next or 1

    def action_earlydryer_allocate_tag_ranges(self):
        """Branch form button: a tag range for each till without one."""
        self.ensure_one()
        Range = self.env["earlydryer.tag.range"]
        Range._earlydryer_check_manager()
        configs = self.sudo().pos_config_ids
        if not configs:
            raise UserError(
                self.env._(
                    "Plant %(branch)s has no point of sale to hold a tag range.",
                    branch=self.display_name,
                )
            )
        active = Range.sudo().search(
            [("pos_config_id", "in", configs.ids), ("state", "=", "active")]
        )
        missing = configs - active.pos_config_id
        if not missing:
            raise UserError(
                self.env._(
                    "Every point of sale of %(branch)s already holds an active tag "
                    "range. New ones are allocated automatically when a range "
                    "runs low.",
                    branch=self.display_name,
                )
            )
        ranges = Range.browse()
        for config in missing:
            ranges |= Range._earlydryer_allocate_range(self, config)
        return self.action_view_tag_ranges()

    def action_view_tag_ranges(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_tagging.earlydryer_tag_range_action"
        )
        action["domain"] = [("branch_id", "=", self.id)]
        action["context"] = {"default_branch_id": self.id}
        return action
