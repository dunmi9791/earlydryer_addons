# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    earlydryer_notify_consent = fields.Boolean(default=True)
    earlydryer_notify_consent_recorded = fields.Boolean()

    @api.model
    def _process_order(self, order, existing_order):
        consent = (
            order.get("earlydryer_notify_consent")
            if order.get("earlydryer_notify_consent_recorded")
            else None
        )
        return super(
            PosOrder, self.with_context(notify_intake_consent=consent)
        )._process_order(order, existing_order)

    @api.model
    def _earlydryer_offline_partner(self, name, phone):
        partner = super()._earlydryer_offline_partner(name, phone)
        consent = self.env.context.get("notify_intake_consent")
        if partner and consent is not None:
            # Never implicitly re-enable an existing STOP when matching an offline customer.
            if not consent or not partner.earlydryer_notify_opt_out:
                partner.write({"earlydryer_notify_opt_in": bool(consent)})
        return partner

    def _earlydryer_after_sync(self):
        result = super()._earlydryer_after_sync()
        for order in self.filtered(lambda o: o.state in ("paid", "done", "invoiced")):
            self.env["earlydryer.notify.message"].notify(
                "payment_received", order, context={"occurrence": str(order.id)}
            )
        return result

    def write(self, vals):
        failed = (
            self.filtered(
                lambda o: o.earlydryer_job_error != vals["earlydryer_job_error"]
            )
            if vals.get("earlydryer_job_error")
            else self.browse()
        )
        result = super().write(vals)
        for order in failed:
            self.env["earlydryer.notify.message"].notify(
                "alert_job_creation_failed",
                order,
                context={"occurrence": str(order.write_date)},
            )
        return result
