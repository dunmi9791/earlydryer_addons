# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    earlydryer_kind = fields.Selection(related="product_id.earlydryer_kind")
    earlydryer_surcharge_ids = fields.Many2many(
        "earlydryer.surcharge",
        "sale_order_line_earlydryer_surcharge_rel",
        "line_id",
        "surcharge_id",
        string="Surcharges",
    )
    earlydryer_parent_line_id = fields.Many2one(
        "sale.order.line",
        string="Garment Line",
        index="btree_not_null",
        ondelete="cascade",
        copy=False,
        help="Surcharge and express lines point to their garment line.",
    )
    earlydryer_child_line_ids = fields.One2many(
        "sale.order.line", "earlydryer_parent_line_id", string="Extra Lines"
    )
    earlydryer_colour = fields.Char(string="Colour")
    earlydryer_condition_note = fields.Text(string="Condition")

    @api.constrains("earlydryer_parent_line_id")
    def _check_earlydryer_parent_line(self):
        for line in self.filtered("earlydryer_parent_line_id"):
            if line.earlydryer_parent_line_id.order_id != line.order_id:
                raise UserError(
                    self.env._("A surcharge line must belong to its garment's order.")
                )

    def action_earlydryer_apply_extras(self):
        """(Re)create the surcharge and express lines of these garment lines.

        Prices come from ``earlydryer.catalog.price_item`` for the order's
        plant, channel and customer; the garment price is aligned too.
        """
        Catalog = self.env["earlydryer.catalog"]
        Job = self.env["laundry.job"]
        for line in self:
            order = line.order_id
            if line.product_id.earlydryer_kind != "laundry":
                raise UserError(
                    self.env._(
                        "%(product)s is not a garment line.",
                        product=line.product_id.display_name,
                    )
                )
            if order.state not in ("draft", "sent"):
                raise UserError(
                    self.env._("Extras can only be changed on a quotation.")
                )
            if not order.earlydryer_branch_id:
                raise UserError(
                    self.env._("Set the plant of %(order)s first.", order=order.name)
                )
            service = line.product_id.earlydryer_service_type_id
            result = Catalog.price_item(
                line.product_id,
                order.partner_id,
                order.earlydryer_branch_id,
                Job._earlydryer_catalog_channel(order.earlydryer_channel),
                surcharges=line.earlydryer_surcharge_ids,
                express=order.earlydryer_express and service.express_available,
                date=order.date_order,
                quantity=line.product_uom_qty,
            )
            extras = [
                (entry["product_id"], entry["unit_price"])
                for entry in result["surcharge_lines"]
            ]
            if result["express_line"]:
                extras.append(
                    (
                        result["express_line"]["product_id"],
                        result["express_line"]["unit_price"],
                    )
                )
            commands = [
                Command.unlink(child.id) for child in line.earlydryer_child_line_ids
            ]
            commands += [
                Command.create(
                    {
                        "product_id": product_id,
                        "product_uom_qty": line.product_uom_qty,
                        "price_unit": unit_price,
                        "sequence": line.sequence,
                        "earlydryer_parent_line_id": line.id,
                    }
                )
                for product_id, unit_price in extras
            ]
            commands.append(
                Command.update(line.id, {"price_unit": result["unit_price"]})
            )
            order.write({"order_line": commands})
        return True
