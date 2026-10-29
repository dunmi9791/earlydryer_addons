# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

SECTIONS = [
    ("account", "Accounts"),
    ("journal", "Journals"),
    ("tax", "Taxes"),
    ("analytic", "Analytics"),
    ("fiscal", "Fiscal Year"),
    ("report", "Reports"),
]
STATUSES = [
    ("create", "Will be created"),
    ("reuse", "Exists: reused"),
    ("skip", "Skipped"),
    ("done", "Created"),
    ("apply", "Applied on confirm"),
]


class EarlydryerAccountingSetupLine(models.TransientModel):
    """One record the setup wizard reuses or creates. Codes and names of the
    records to create can be edited before confirming."""

    _name = "earlydryer.accounting.setup.line"
    _description = "Earlydryer Accounting Setup Line"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "earlydryer.accounting.setup.wizard", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)
    section = fields.Selection(SECTIONS, required=True, default="account")
    key = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True)
    code = fields.Char()
    account_type = fields.Char(string="Type", readonly=True)
    reconcile = fields.Boolean(readonly=True)
    branch_id = fields.Many2one("earlydryer.branch", string="Plant", readonly=True)
    status = fields.Selection(STATUSES, required=True, default="create")
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    existing = fields.Char(string="Existing Record", compute="_compute_existing")
    editable = fields.Boolean(default=True, readonly=True)
    note = fields.Char(readonly=True)

    @api.depends("res_model", "res_id")
    def _compute_existing(self):
        for line in self:
            if line.res_model and line.res_id:
                record = self.env[line.res_model].sudo().browse(line.res_id).exists()
                line.existing = record.display_name if record else False
            else:
                line.existing = False

    def _record(self):
        self.ensure_one()
        if not (self.res_model and self.res_id):
            return False
        return self.env[self.res_model].sudo().browse(self.res_id).exists()
