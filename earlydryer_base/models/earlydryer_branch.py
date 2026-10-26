# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EarlydryerBranch(models.Model):
    _name = "earlydryer.branch"
    _description = "Earlydryer Branch (Plant)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, name"
    _rec_names_search = ["name", "code"]
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(
        required=True,
        size=5,
        tracking=True,
        help="Short upper-case code, used as a prefix for job and tag numbers.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Address",
        check_company=True,
        help="Plant address, phone and email.",
    )
    phone = fields.Char(related="partner_id.phone")
    email = fields.Char(related="partner_id.email")
    manager_id = fields.Many2one(
        "res.users",
        string="Branch Manager",
        tracking=True,
        domain=[("share", "=", False)],
    )
    user_ids = fields.Many2many(
        "res.users",
        "earlydryer_branch_res_users_rel",
        "branch_id",
        "user_id",
        string="Staff",
        domain=[("share", "=", False)],
        help="Users allowed to work on this branch.",
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        check_company=True,
        tracking=True,
    )
    pos_config_ids = fields.One2many(
        "pos.config",
        "earlydryer_branch_id",
        string="Points of Sale",
    )
    pos_config_count = fields.Integer(compute="_compute_pos_config_count")
    cash_journal_id = fields.Many2one(
        "account.journal",
        domain=[("type", "=", "cash")],
        check_company=True,
        tracking=True,
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        check_company=True,
        tracking=True,
    )
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Operating Hours",
        check_company=True,
    )
    shelf_ids = fields.One2many(
        "earlydryer.branch.shelf",
        "branch_id",
        string="Shelves",
    )
    shelf_count = fields.Integer(compute="_compute_shelf_count")
    note = fields.Html()

    _code_company_uniq = models.Constraint(
        "unique(company_id, code)",
        "The branch code must be unique per company.",
    )

    @api.depends("name", "code")
    def _compute_display_name(self):
        for branch in self:
            branch.display_name = (
                f"{branch.code} - {branch.name}" if branch.code else branch.name
            )

    @api.depends("shelf_ids")
    def _compute_shelf_count(self):
        data = self.env["earlydryer.branch.shelf"]._read_group(
            [("branch_id", "in", self.ids)], ["branch_id"], ["__count"]
        )
        counts = {branch.id: count for branch, count in data}
        for branch in self:
            branch.shelf_count = counts.get(branch.id, 0)

    @api.depends("pos_config_ids")
    def _compute_pos_config_count(self):
        for branch in self:
            branch.pos_config_count = len(branch.pos_config_ids)

    @api.constrains("warehouse_id", "cash_journal_id", "analytic_account_id")
    def _check_unique_links(self):
        messages = {
            "warehouse_id": self.env._(
                "Warehouse %(record)s is already used by branch %(branch)s."
            ),
            "cash_journal_id": self.env._(
                "Cash journal %(record)s is already used by branch %(branch)s."
            ),
            "analytic_account_id": self.env._(
                "Analytic account %(record)s is already used by branch %(branch)s."
            ),
        }
        branches = self.sudo().with_context(active_test=False)
        for fname, message in messages.items():
            for branch in branches.filtered(fname):
                other = branches.search(
                    [(fname, "=", branch[fname].id), ("id", "!=", branch.id)],
                    limit=1,
                )
                if other:
                    raise ValidationError(
                        message
                        % {
                            "record": branch[fname].display_name,
                            "branch": other.display_name,
                        }
                    )

    @api.model
    def _normalize_vals(self, vals):
        if vals.get("code"):
            vals["code"] = vals["code"].strip().upper()
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._normalize_vals(dict(vals)) for vals in vals_list]
        branches = super().create(vals_list)
        if any(vals.get("user_ids") for vals in vals_list):
            # record rules depend on the users' allowed branches
            self.env.registry.clear_cache()
        return branches

    def write(self, vals):
        vals = self._normalize_vals(dict(vals))
        if "active" in vals and not vals["active"]:
            self.shelf_ids.filtered("active").write({"active": False})
        res = super().write(vals)
        if "user_ids" in vals:
            self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _generate_shelves(self, prefix, start=1, count=10, padding=2, separator="-"):
        """Create shelves ``<prefix><separator><number>`` on each branch.

        Names that already exist on the branch (archived included) are skipped.
        Returns the created shelves.
        """
        Shelf = self.env["earlydryer.branch.shelf"]
        prefix = (prefix or "").strip()
        separator = separator or ""
        names = [
            f"{prefix}{separator}{str(number).zfill(padding)}"
            for number in range(start, start + count)
        ]
        shelves = Shelf
        for branch in self:
            existing = Shelf.with_context(active_test=False).search(
                [("branch_id", "=", branch.id)]
            )
            existing_names = set(existing.mapped("name"))
            next_sequence = max(existing.mapped("sequence") or [0]) + 1
            vals_list = []
            for name in names:
                if name in existing_names:
                    continue
                vals_list.append(
                    {"branch_id": branch.id, "name": name, "sequence": next_sequence}
                )
                next_sequence += 1
            shelves |= Shelf.create(vals_list)
        return shelves

    def action_open_generate_shelves(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Generate Shelves"),
            "res_model": "earlydryer.branch.shelf.generate",
            "view_mode": "form",
            "target": "new",
            "context": {"default_branch_id": self.id},
        }

    def action_view_shelves(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_base.earlydryer_branch_shelf_action"
        )
        action["domain"] = [("branch_id", "=", self.id)]
        action["context"] = {"default_branch_id": self.id}
        return action

    def action_view_pos_configs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Points of Sale"),
            "res_model": "pos.config",
            "view_mode": "list,form",
            "domain": [("earlydryer_branch_id", "=", self.id)],
            "context": {"default_earlydryer_branch_id": self.id},
        }
