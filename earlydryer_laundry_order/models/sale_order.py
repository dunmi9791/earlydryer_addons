# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError

from .laundry_job import CHANNELS, FULFILMENTS

JOB_READERS = (
    "earlydryer_base.group_front_desk,earlydryer_base.group_production,"
    "earlydryer_base.group_rider,earlydryer_base.group_customer_service,"
    "earlydryer_base.group_finance"
)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # not required here so that other sales are unaffected: required in the
    # view and on confirmation of an order with laundry lines
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Plant",
        index="btree_not_null",
        tracking=True,
        ondelete="restrict",
        default=lambda self: self.env[
            "earlydryer.branch.mixin"
        ]._default_earlydryer_branch_id(),
    )
    earlydryer_channel = fields.Selection(CHANNELS, string="Channel", default="pickup")
    earlydryer_fulfilment = fields.Selection(
        FULFILMENTS, string="Fulfilment", default="deliver"
    )
    earlydryer_express = fields.Boolean(string="Express")
    earlydryer_has_laundry = fields.Boolean(compute="_compute_earlydryer_has_laundry")
    laundry_job_ids = fields.One2many(
        "laundry.job", "sale_order_id", string="Laundry Jobs", groups=JOB_READERS
    )
    laundry_job_count = fields.Integer(
        compute="_compute_laundry_job_count", compute_sudo=True
    )

    @api.depends("order_line.product_id")
    def _compute_earlydryer_has_laundry(self):
        for order in self:
            order.earlydryer_has_laundry = any(
                line.product_id.earlydryer_kind == "laundry"
                for line in order.order_line
            )

    def _compute_laundry_job_count(self):
        data = self.env["laundry.job"]._read_group(
            [("sale_order_id", "in", self.ids)], ["sale_order_id"], ["__count"]
        )
        counts = {order.id: count for order, count in data}
        for order in self:
            order.laundry_job_count = counts.get(order.id, 0)

    @api.depends(
        "partner_id", "company_id", "earlydryer_branch_id", "earlydryer_channel"
    )
    def _compute_pricelist_id(self):
        res = super()._compute_pricelist_id()
        Pricelist = self.env["product.pricelist"]
        Job = self.env["laundry.job"]
        for order in self:
            if order.state != "draft" or not order.partner_id:
                continue
            if not order.earlydryer_branch_id or not order.earlydryer_channel:
                continue
            pricelist = Pricelist._earlydryer_resolve_pricelist(
                order.partner_id,
                order.earlydryer_branch_id,
                Job._earlydryer_catalog_channel(order.earlydryer_channel),
            )
            if pricelist:
                order.pricelist_id = pricelist
        return res

    def _earlydryer_laundry_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: line.product_id.earlydryer_kind == "laundry"
        )

    def action_confirm(self):
        for order in self:
            if order._earlydryer_laundry_lines() and not order.earlydryer_branch_id:
                raise UserError(
                    self.env._(
                        "Set the plant of %(order)s: it contains laundry items.",
                        order=order.name,
                    )
                )
        return super().action_confirm()

    def _action_confirm(self):
        res = super()._action_confirm()
        self._earlydryer_create_laundry_jobs()
        return res

    def _earlydryer_job_line_vals(self, line):
        return {
            "product_id": line.product_id,
            "quantity": line.product_uom_qty,
            "price_unit": line.price_unit,
            "surcharge_ids": line.earlydryer_surcharge_ids,
            "colour": line.earlydryer_colour,
            "condition_note": line.earlydryer_condition_note,
            "source_line_id": line.id,
        }

    def _earlydryer_create_laundry_jobs(self):
        """Create the laundry job of each confirmed order (once per order)."""
        # sudo: the job is generated from the order, whoever confirms it
        # (front desk, customer service, website checkout)
        Job = self.env["laundry.job"].sudo()
        jobs = Job
        for order in self:
            lines = order._earlydryer_laundry_lines()
            if not lines:
                continue
            jobs |= Job._earlydryer_create_from_lines(
                order.partner_id,
                order.earlydryer_branch_id,
                order.earlydryer_channel or "pickup",
                order.earlydryer_fulfilment or "collect",
                order.earlydryer_express,
                [order._earlydryer_job_line_vals(line) for line in lines],
                source=order,
            )
        return jobs

    def action_earlydryer_apply_extras(self):
        """Add the surcharge and express lines of every garment line."""
        for order in self:
            order._earlydryer_laundry_lines().action_earlydryer_apply_extras()
        return True

    def action_view_laundry_jobs(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "earlydryer_laundry_order.laundry_job_action"
        )
        jobs = self.laundry_job_ids
        if len(jobs) == 1:
            action.update(views=[(False, "form")], res_id=jobs.id)
        else:
            action["domain"] = [("sale_order_id", "=", self.id)]
        action["context"] = {}
        return action
