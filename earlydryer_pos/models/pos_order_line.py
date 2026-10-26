# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    earlydryer_parent_line_uuid = fields.Char(
        string="Garment Line UUID",
        help="Client uuid of the garment line a surcharge or express line "
        "belongs to (set by the till).",
    )
    earlydryer_parent_line_id = fields.Many2one(
        "pos.order.line",
        string="Garment Line",
        readonly=True,
        index="btree_not_null",
        ondelete="cascade",
        help="Resolved from the garment line uuid at sync.",
    )
    earlydryer_child_line_ids = fields.One2many(
        "pos.order.line",
        "earlydryer_parent_line_id",
        string="Surcharge and Express Lines",
    )
    earlydryer_surcharge_id = fields.Many2one(
        "earlydryer.surcharge", string="Surcharge", ondelete="restrict"
    )
    earlydryer_colour = fields.Char(string="Colour")
    earlydryer_brand = fields.Char(string="Brand")
    earlydryer_condition_note = fields.Text(string="Condition")
    earlydryer_tag_codes = fields.Char(
        string="Tag Codes", help="One tag code per piece, comma-separated."
    )
    earlydryer_photo_count = fields.Integer(
        string="Photos Taken", help="Condition photos taken at the till."
    )
    earlydryer_discount_approver_employee_id = fields.Many2one(
        "hr.employee",
        string="Discount Approved By",
        help="Employee whose PIN approved the discount at the till.",
    )
    earlydryer_discount_rule_id = fields.Many2one(
        "earlydryer.approval.rule", string="Discount Rule", ondelete="set null"
    )
    earlydryer_settlement_job_ref = fields.Char(
        string="Settled Job Reference",
        help="Id of the laundry job whose balance this settlement line pays "
        "(set by the till).",
    )
    earlydryer_settlement_job_id = fields.Many2one(
        "laundry.job", string="Settled Job", readonly=True, index="btree_not_null"
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        return [
            *fields_list,
            "earlydryer_parent_line_uuid",
            "earlydryer_surcharge_id",
            "earlydryer_colour",
            "earlydryer_brand",
            "earlydryer_condition_note",
            "earlydryer_tag_codes",
            "earlydryer_photo_count",
            "earlydryer_discount_approver_employee_id",
            "earlydryer_discount_rule_id",
            "earlydryer_settlement_job_ref",
        ]

    def _earlydryer_resolve_parent_lines(self):
        """Link surcharge and express lines to their garment line."""
        for line in self.filtered("earlydryer_parent_line_uuid"):
            parent = line.order_id.lines.filtered(
                lambda other, line=line: other.uuid == line.earlydryer_parent_line_uuid
            )[:1]
            if parent != line.earlydryer_parent_line_id:
                line.earlydryer_parent_line_id = parent

    def _earlydryer_tag_code_list(self):
        self.ensure_one()
        return [
            code.strip().upper()
            for code in (self.earlydryer_tag_codes or "").split(",")
            if code.strip()
        ]
