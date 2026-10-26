# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command


class EarlydryerCloseChecklist(models.Model):
    """Month-end close of one period: steps the accountant ticks, most of
    them with an automatic check."""

    _name = "earlydryer.close.checklist"
    _description = "Earlydryer Month-end Checklist"
    _inherit = ["mail.thread"]
    _order = "date_from desc, id desc"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    date_range_id = fields.Many2one(
        "date.range",
        string="Period",
        check_company=True,
        domain="[('type_id.earlydryer_period_type', '=', True)]",
    )
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1)
        - relativedelta(months=1),
    )
    date_to = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1)
        - relativedelta(days=1),
    )
    state = fields.Selection(
        [("open", "Open"), ("done", "Closed")],
        default="open",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        "earlydryer.close.checklist.line", "checklist_id", string="Steps", copy=True
    )
    progress = fields.Float(compute="_compute_progress")
    note = fields.Html()

    _period_uniq = models.Constraint(
        "unique(company_id, date_from, date_to)",
        "There is already a checklist for this period.",
    )

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for checklist in self:
            if checklist.date_from:
                checklist.name = self.env._(
                    "Close %(period)s", period=checklist.date_from.strftime("%B %Y")
                )
            else:
                checklist.name = self.env._("Month-end close")

    @api.depends("line_ids.done")
    def _compute_progress(self):
        for checklist in self:
            lines = checklist.line_ids
            checklist.progress = (
                100.0 * len(lines.filtered("done")) / len(lines) if lines else 0.0
            )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for checklist in self:
            if checklist.date_from > checklist.date_to:
                raise ValidationError(self.env._("The period ends before it starts."))

    @api.onchange("date_range_id")
    def _onchange_date_range_id(self):
        if self.date_range_id:
            self.date_from = self.date_range_id.date_start
            self.date_to = self.date_range_id.date_end

    @api.model
    def _earlydryer_check_right(self, write=True):
        user = self.env.user
        if self.env.su or user.has_group("earlydryer_base.group_finance"):
            return True
        if not write and user.has_group("earlydryer_base.group_management"):
            return True
        raise AccessError(self.env._("The month-end checklist is for Finance."))

    @api.model_create_multi
    def create(self, vals_list):
        self._earlydryer_check_right()
        items = self.env["earlydryer.close.checklist.item"].search([])
        for vals in vals_list:
            if "line_ids" not in vals:
                vals["line_ids"] = [
                    Command.create(
                        {"item_id": item.id, "name": item.name, "sequence": item.sequence}
                    )
                    for item in items
                ]
        return super().create(vals_list)

    def write(self, vals):
        self._earlydryer_check_right()
        return super().write(vals)

    def action_check_all(self):
        self.line_ids.filtered(lambda line: line.check_code != "manual").action_check()
        return True

    def action_close(self):
        self.write({"state": "done"})
        return True

    def action_reopen(self):
        self.write({"state": "open"})
        return True
