# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .laundry_job import CORRECTION_CTX, MANAGER_GROUP

# fields that stay editable after intake (tagging, QC, packing)
OPEN_FIELDS = {
    "tag_code",
    "qc_state",
    "missing",
    "condition_note",
    "photo_ids",
    "rework_count",
    "qc_employee_id",
    "qc_date",
    "sequence",
}


class LaundryJobItem(models.Model):
    _name = "laundry.job.item"
    _description = "Laundry Job Item (Garment)"
    _order = "job_id, sequence, id"
    _rec_names_search = ["tag_code", "product_id", "job_id"]

    job_id = fields.Many2one(
        "laundry.job", required=True, index=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)
    earlydryer_branch_id = fields.Many2one(
        related="job_id.earlydryer_branch_id", store=True, index=True
    )
    company_id = fields.Many2one(related="job_id.company_id", store=True)
    job_state = fields.Selection(related="job_id.state", store=True, string="Job Stage")
    product_id = fields.Many2one(
        "product.product",
        string="Garment & Service",
        required=True,
        domain=[("earlydryer_kind", "=", "laundry")],
    )
    garment_category_id = fields.Many2one(
        related="product_id.earlydryer_garment_category_id", store=True, index=True
    )
    service_type_id = fields.Many2one(
        related="product_id.earlydryer_service_type_id", store=True, index=True
    )
    piece_index = fields.Integer(
        string="Piece", default=1, help="1..n for the pieces of a multi-piece garment."
    )
    piece_count = fields.Integer(
        string="Pieces", default=1, help="Number of pieces of the garment."
    )
    surcharge_ids = fields.Many2many(
        "earlydryer.surcharge",
        "laundry_job_item_surcharge_rel",
        "item_id",
        "surcharge_id",
        string="Surcharges",
    )
    express = fields.Boolean(related="job_id.express")
    tag_code = fields.Char(
        string="Tag", index="btree_not_null", copy=False, help="Garment tag number."
    )
    colour = fields.Char()
    brand = fields.Char()
    condition_note = fields.Text(
        string="Condition", help="Stains, tears, missing buttons... at intake."
    )
    photo_ids = fields.Many2many(
        "ir.attachment",
        "laundry_job_item_attachment_rel",
        "item_id",
        "attachment_id",
        string="Photos",
    )
    currency_id = fields.Many2one(related="job_id.currency_id")
    price_unit = fields.Monetary(
        string="Price",
        readonly=True,
        help="Garment price at intake, copied from the order line. A garment "
        "of several pieces carries its price on piece 1.",
    )
    sale_line_id = fields.Many2one(
        "sale.order.line", index="btree_not_null", ondelete="set null", copy=False
    )
    pos_line_id = fields.Many2one(
        "pos.order.line", index="btree_not_null", ondelete="set null", copy=False
    )
    qc_state = fields.Selection(
        [("pending", "Pending"), ("passed", "Passed"), ("rework", "Rework")],
        string="QC",
        required=True,
        default="pending",
        copy=False,
    )
    qc_employee_id = fields.Many2one(
        "hr.employee", string="Checked By", readonly=True, copy=False
    )
    qc_date = fields.Datetime(string="Checked On", readonly=True, copy=False)
    rework_count = fields.Integer(readonly=True, copy=False)
    missing = fields.Boolean(
        copy=False, help="The item cannot be found at packing (a claim follows)."
    )

    _tag_branch_uniq = models.UniqueIndex(
        "(earlydryer_branch_id, tag_code) WHERE tag_code IS NOT NULL",
        "This tag is already used in this plant.",
    )

    @api.depends("product_id", "piece_index", "piece_count", "tag_code")
    def _compute_display_name(self):
        for item in self:
            name = item.product_id.display_name or ""
            if item.piece_count > 1:
                name = f"{name} ({item.piece_index}/{item.piece_count})"
            if item.tag_code:
                name = f"[{item.tag_code}] {name}"
            item.display_name = name

    # ------------------------------------------------------------------
    # Locking after intake
    # ------------------------------------------------------------------

    def _earlydryer_is_manager(self):
        return self.env.su or self.env.user.has_group(MANAGER_GROUP)

    def _earlydryer_check_locked(self, jobs, fnames=None):
        """Items of ``jobs`` past Received only change through OPEN_FIELDS;
        Branch Managers may correct them with a reason (logged)."""
        locked_jobs = jobs.filtered(lambda job: job.state != "received")
        if not locked_jobs or self.env.su:
            return
        if fnames is not None and set(fnames) <= OPEN_FIELDS:
            return
        if not self.env.user.has_group(MANAGER_GROUP):
            raise UserError(
                self.env._(
                    "The items of job %(job)s are locked after intake. Ask a "
                    "Branch Manager to correct them.",
                    job=locked_jobs[0].name,
                )
            )
        reason = self.env.context.get(CORRECTION_CTX)
        if not reason:
            raise UserError(
                self.env._(
                    "Give a correction reason to change the items of job %(job)s "
                    "after intake.",
                    job=locked_jobs[0].name,
                )
            )
        for job in locked_jobs:
            job.message_post(
                body=self.env._("Items corrected: %(reason)s", reason=reason),
                subtype_xmlid="mail.mt_note",
            )

    @api.model_create_multi
    def create(self, vals_list):
        job_ids = {vals["job_id"] for vals in vals_list if vals.get("job_id")}
        self._earlydryer_check_locked(self.env["laundry.job"].browse(job_ids))
        return super().create(vals_list)

    def write(self, vals):
        if "price_unit" in vals and not self._earlydryer_is_manager():
            raise AccessError(
                self.env._("Only a Branch Manager can change an item price.")
            )
        self._earlydryer_check_locked(self.job_id, vals.keys())
        if "missing" in vals:
            changed = self.filtered(lambda item: item.missing != bool(vals["missing"]))
        res = super().write(vals)
        if "missing" in vals:
            for item in changed:
                if item.missing:
                    body = self.env._(
                        "Item %(item)s flagged missing.", item=item.display_name
                    )
                else:
                    body = self.env._("Item %(item)s found.", item=item.display_name)
                item.job_id.message_post(body=body, subtype_xmlid="mail.mt_note")
        return res

    def unlink(self):
        self._earlydryer_check_locked(self.job_id)
        return super().unlink()
