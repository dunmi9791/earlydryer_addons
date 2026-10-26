# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    earlydryer_vat_registered = fields.Boolean(
        related="company_id.earlydryer_vat_registered", readonly=False
    )
    earlydryer_prices_include_vat = fields.Boolean(
        related="company_id.earlydryer_prices_include_vat", readonly=False
    )
    earlydryer_einvoice_enabled = fields.Boolean(
        related="company_id.earlydryer_einvoice_enabled", readonly=False
    )
    earlydryer_tax_authority_id = fields.Many2one(
        related="company_id.earlydryer_tax_authority_id", readonly=False
    )
    earlydryer_invoice_footer = fields.Text(
        related="company_id.earlydryer_invoice_footer", readonly=False
    )
    earlydryer_vat_pending = fields.Boolean(compute="_compute_earlydryer_vat_pending")
    earlydryer_is_live = fields.Boolean(compute="_compute_earlydryer_vat_pending")

    @api.depends("earlydryer_vat_registered", "earlydryer_prices_include_vat")
    def _compute_earlydryer_vat_pending(self):
        for settings in self:
            company = settings.company_id
            state = (
                f"{int(settings.earlydryer_vat_registered)}/"
                f"{int(settings.earlydryer_prices_include_vat)}"
            )
            settings.earlydryer_vat_pending = state != (
                company.earlydryer_vat_applied_state or "0/1"
            )
            settings.earlydryer_is_live = company._earlydryer_is_live()

    @api.onchange("earlydryer_vat_registered", "earlydryer_prices_include_vat")
    def _onchange_earlydryer_vat(self):
        if self.earlydryer_vat_pending and self.earlydryer_is_live:
            return {
                "warning": {
                    "title": self.env._("VAT setting"),
                    "message": self.env._(
                        "Documents were already issued. The change affects new "
                        "documents only, after 'Apply VAT setting': posted invoices "
                        "and open orders keep their taxes."
                    ),
                }
            }
        return None

    def action_earlydryer_apply_vat(self):
        self.execute()
        self.env["earlydryer.accounting.setup.wizard"]._earlydryer_check_setup_right()
        summary = self.company_id._earlydryer_apply_vat_setting()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("VAT setting applied"),
                "message": "\n".join(summary),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_earlydryer_accounting_setup(self):
        self.execute()
        return self.env["earlydryer.accounting.setup.wizard"].action_open()
