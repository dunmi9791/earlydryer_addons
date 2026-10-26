# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class EarlydryerWhtRemovalWizard(models.TransientModel):
    """Take WHT off bill lines (exempt goods...), with the reason logged."""

    _name = "earlydryer.wht.removal.wizard"
    _description = "Remove WHT from Bill Lines"

    move_id = fields.Many2one("account.move", required=True)
    line_ids = fields.Many2many(
        "account.move.line",
        string="Lines",
        domain="[('move_id', '=', move_id), "
        "('tax_ids.earlydryer_wht_category_id', '!=', False)]",
    )
    reason = fields.Char(required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move = self.env["account.move"].browse(res.get("move_id"))
        if move and "line_ids" in fields_list:
            lines = move.invoice_line_ids.filtered(
                lambda line: line.tax_ids.filtered("earlydryer_wht_category_id")
            )
            res["line_ids"] = [(6, 0, lines.ids)]
        return res

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards.filtered(lambda w: not w.line_ids):
            wizard.line_ids = wizard.move_id.invoice_line_ids.filtered(
                lambda line: line.tax_ids.filtered("earlydryer_wht_category_id")
            )
        return wizards

    def action_remove(self):
        self.ensure_one()
        self.line_ids._earlydryer_remove_wht(self.reason)
        return {"type": "ir.actions.act_window_close"}
