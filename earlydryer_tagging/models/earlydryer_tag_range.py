# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

MANAGER_GROUP = "earlydryer_base.group_branch_manager"
DEFAULT_RANGE_SIZE = 500
# a till gets its next range when fewer than this share of numbers is left
TOP_UP_RATIO = 0.2


class EarlydryerTagRange(models.Model):
    """Block of printed tag numbers held by a till for offline intake.

    The numbers are taken from the plant's tag sequence in one go, so the
    codes the till prints offline never collide with the codes assigned on
    the server. earlydryer_pos loads the till's active ranges into the POS
    session; this model only keeps track of them.
    """

    _name = "earlydryer.tag.range"
    _description = "Earlydryer Tag Range"
    _order = "branch_id, start_number"

    name = fields.Char(compute="_compute_name", store=True)
    branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        required=True,
        index=True,
        readonly=True,
        ondelete="restrict",
    )
    company_id = fields.Many2one(related="branch_id.company_id", store=True)
    pos_config_id = fields.Many2one(
        "pos.config",
        string="Point of Sale",
        index="btree_not_null",
        ondelete="set null",
        help="Till holding the range.",
    )
    start_number = fields.Integer(required=True, readonly=True)
    end_number = fields.Integer(required=True, readonly=True)
    next_number = fields.Integer(
        required=True,
        readonly=True,
        help="First number not used yet by the till.",
    )
    size = fields.Integer(compute="_compute_counts")
    remaining_count = fields.Integer(string="Left", compute="_compute_counts")
    first_code = fields.Char(compute="_compute_codes")
    last_code = fields.Char(compute="_compute_codes")
    state = fields.Selection(
        [("active", "Active"), ("exhausted", "Exhausted"), ("cancelled", "Cancelled")],
        required=True,
        default="active",
        index=True,
        readonly=True,
    )
    allocated_on = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )
    allocated_by = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, readonly=True
    )

    _numbers_ordered = models.Constraint(
        "CHECK(start_number > 0 AND end_number >= start_number "
        "AND next_number >= start_number AND next_number <= end_number + 1)",
        "A tag range goes from its first to its last number.",
    )

    @api.depends("branch_id.tag_prefix", "start_number", "end_number")
    def _compute_name(self):
        for tag_range in self:
            tag_range.name = (
                f"{tag_range.branch_id.tag_prefix or ''} "
                f"{tag_range.start_number}-{tag_range.end_number}"
            )

    @api.depends("start_number", "end_number", "next_number")
    def _compute_counts(self):
        for tag_range in self:
            tag_range.size = tag_range.end_number - tag_range.start_number + 1
            tag_range.remaining_count = max(
                tag_range.end_number - tag_range.next_number + 1, 0
            )

    @api.depends("branch_id", "start_number", "end_number")
    def _compute_codes(self):
        TagCode = self.env["earlydryer.tag.code"]
        for tag_range in self:
            branch = tag_range.branch_id
            if branch.tag_prefix and tag_range.start_number:
                tag_range.first_code = TagCode.format_number(
                    branch, tag_range.start_number
                )
                tag_range.last_code = TagCode.format_number(
                    branch, tag_range.end_number
                )
            else:
                tag_range.first_code = tag_range.last_code = False

    @api.constrains("branch_id", "start_number", "end_number")
    def _check_overlap(self):
        for tag_range in self:
            other = self.sudo().search(
                [
                    ("id", "!=", tag_range.id),
                    ("branch_id", "=", tag_range.branch_id.id),
                    ("start_number", "<=", tag_range.end_number),
                    ("end_number", ">=", tag_range.start_number),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(
                    self.env._(
                        "Tag range %(range)s overlaps range %(other)s of the same "
                        "plant.",
                        range=tag_range.name,
                        other=other.name,
                    )
                )

    @api.constrains("branch_id", "pos_config_id")
    def _check_pos_config_branch(self):
        for tag_range in self.filtered("pos_config_id"):
            if tag_range.pos_config_id.earlydryer_branch_id != tag_range.branch_id:
                raise ValidationError(
                    self.env._(
                        "Point of sale %(pos)s does not belong to plant %(branch)s.",
                        pos=tag_range.pos_config_id.display_name,
                        branch=tag_range.branch_id.display_name,
                    )
                )

    # ------------------------------------------------------------------
    # Allocation and consumption
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_check_manager(self):
        if not self.env.su and not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(
                self.env._("Only a Branch Manager can allocate or cancel tag ranges.")
            )

    @api.model
    def _earlydryer_allocate_range(
        self, branch, pos_config=None, size=DEFAULT_RANGE_SIZE
    ):
        """Take ``size`` numbers of ``branch``'s tag sequence in one block.

        :param branch: ``earlydryer.branch`` in printed mode
        :param pos_config: ``pos.config`` holding the range (optional)
        :returns: the new ``earlydryer.tag.range``
        """
        self._earlydryer_check_manager()
        branch.ensure_one()
        if branch.tag_mode != "printed":
            raise UserError(
                self.env._(
                    "Plant %(branch)s uses pre-printed tags: it needs no tag range.",
                    branch=branch.display_name,
                )
            )
        if size < 1:
            raise UserError(self.env._("A tag range holds at least one number."))
        first = branch._earlydryer_tag_take_numbers(size)
        tag_range = self.sudo().create(
            {
                "branch_id": branch.id,
                "pos_config_id": pos_config.id if pos_config else False,
                "start_number": first,
                "end_number": first + size - 1,
                "next_number": first,
                "allocated_by": self.env.uid,
            }
        )
        return tag_range.with_env(self.env)

    @api.model
    def _earlydryer_consume(self, code, branch=None):
        """Record that a printed ``code`` is now on a garment.

        A code of a range advances its next number (the range becomes
        exhausted after its last number). A code outside every range is
        accepted only if the plant's sequence already issued it (a tag
        assigned on the server). Pre-printed plants have no ranges.

        :returns: the range of the code (empty when none)
        :raises ValidationError: for a code never issued or of a cancelled range
        """
        TagCode = self.env["earlydryer.tag.code"]
        branch = branch or TagCode.branch_for(code)
        if not branch or branch.tag_mode != "printed":
            return self.browse()
        number = TagCode.number_for(code, branch)
        if number is None:
            raise ValidationError(
                self.env._(
                    "%(code)s is not a valid tag code of plant %(branch)s.",
                    code=code,
                    branch=branch.display_name,
                )
            )
        tag_range = self.sudo().search(
            [
                ("branch_id", "=", branch.id),
                ("start_number", "<=", number),
                ("end_number", ">=", number),
            ],
            limit=1,
        )
        if not tag_range:
            if number >= branch._earlydryer_tag_next_number():
                raise ValidationError(
                    self.env._(
                        "Tag %(code)s was never issued by plant %(branch)s.",
                        code=code,
                        branch=branch.display_name,
                    )
                )
            return self.browse()
        if tag_range.state == "cancelled":
            raise ValidationError(
                self.env._(
                    "Tag %(code)s belongs to the cancelled range %(range)s.",
                    code=code,
                    range=tag_range.name,
                )
            )
        vals = {}
        if number >= tag_range.next_number:
            vals["next_number"] = number + 1
        if number >= tag_range.end_number:
            vals["state"] = "exhausted"
        if vals:
            tag_range.write(vals)
        return tag_range.with_env(self.env)

    def action_cancel(self):
        """Cancel ranges a till will not use (lost device...); numbers stay taken."""
        self._earlydryer_check_manager()
        self.filtered(lambda r: r.state == "active").sudo().write(
            {"state": "cancelled"}
        )
        return True

    # ------------------------------------------------------------------
    # Top-up
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_top_up(self, pos_configs=None):
        """Allocate the next range of the tills running low (or without any).

        Called daily by a cron and when a POS session opens.
        :returns: the new ranges
        """
        configs = (
            pos_configs
            or self.env["pos.config"].search(
                [("earlydryer_branch_id.tag_mode", "=", "printed")]
            )
        ).sudo()
        configs = configs.filtered(
            lambda c: (
                c.earlydryer_branch_id and c.earlydryer_branch_id.tag_mode == "printed"
            )
        )
        new = self.browse()
        if not configs:
            return new
        ranges = self.sudo().search([("pos_config_id", "in", configs.ids)])
        for config in configs:
            config_ranges = ranges.filtered(lambda r, c=config: r.pos_config_id == c)
            active = config_ranges.filtered(lambda r: r.state == "active")
            size = (
                config_ranges.sorted("start_number")[-1:].size
            ) or DEFAULT_RANGE_SIZE
            left = sum(active.mapped("remaining_count"))
            if active and left >= size * TOP_UP_RATIO:
                continue
            new |= self.sudo()._earlydryer_allocate_range(
                config.earlydryer_branch_id, config, size=size
            )
            _logger.info(
                "Tag range allocated to %s (%s numbers left).",
                config.display_name,
                left,
            )
        return new

    @api.model
    def _cron_earlydryer_top_up(self):
        self.sudo()._earlydryer_top_up()
        return True

    def _earlydryer_pos_data(self):
        """Plain values of the ranges for the POS session (earlydryer_pos)."""
        return [
            {
                "id": tag_range.id,
                "prefix": tag_range.branch_id.tag_prefix,
                "check_digit": tag_range.branch_id.tag_check_digit,
                "start_number": tag_range.start_number,
                "end_number": tag_range.end_number,
                "next_number": tag_range.next_number,
            }
            for tag_range in self
        ]
