# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from ..models.earlydryer_logistics_stop import COLLECTION_METHODS


class EarlydryerLogisticsOutcomeWizard(models.TransientModel):
    """Outcome of a stop recorded by the office: 3PL trips, riders without a
    login, phone fallback. Same proof fields as the rider view."""

    _name = "earlydryer.logistics.outcome.wizard"
    _description = "Earlydryer Record Stop Outcome"

    stop_id = fields.Many2one("earlydryer.logistics.stop", required=True)
    stop_type = fields.Selection(related="stop_id.stop_type")
    currency_id = fields.Many2one(related="stop_id.currency_id")
    cod_amount = fields.Monetary(related="stop_id.cod_amount")
    outcome = fields.Selection(
        [("done", "Done"), ("failed", "Failed")], required=True, default="done"
    )
    recipient_name = fields.Char()
    signature = fields.Binary()
    attachment_ids = fields.Many2many("ir.attachment", string="Photos / Carrier Proof")
    cash_collected = fields.Monetary()
    collection_method = fields.Selection(COLLECTION_METHODS, default="cash")
    transfer_amount = fields.Monetary()
    office_credit = fields.Boolean(
        string="Approve Credit Now",
        help="Short collection: approve the credit on the job yourself (credit "
        "rule of the plant).",
    )
    bag_count = fields.Integer()
    piece_count_estimate = fields.Integer()
    pickup_note = fields.Char()
    fail_reason_id = fields.Many2one("earlydryer.logistics.fail.reason")
    fail_note = fields.Text()

    @api.onchange("stop_id")
    def _onchange_stop_id(self):
        if self.stop_id.stop_type == "delivery":
            self.cash_collected = self.stop_id.cod_amount
            self.collection_method = "cash" if self.stop_id.cod_amount else "none"

    def action_confirm(self):
        self.ensure_one()
        stop = self.stop_id
        stop._earlydryer_check_right("outcome", stop.earlydryer_branch_id)
        stop = stop.sudo()
        if self.attachment_ids:
            self.attachment_ids.sudo().write(
                {"res_model": stop._name, "res_id": stop.id}
            )
            stop.photo_ids = [Command.link(a.id) for a in self.attachment_ids]
        if self.outcome == "failed":
            if not self.fail_reason_id:
                raise UserError(self.env._("Give the reason of the failure."))
            stop._earlydryer_fail(self.fail_reason_id, note=self.fail_note)
            return True
        vals = {
            "recipient_name": self.recipient_name,
            "signature": self.signature,
            "bag_count": self.bag_count,
            "piece_count_estimate": self.piece_count_estimate,
            "pickup_note": self.pickup_note,
            "cash_collected": self.cash_collected
            if self.collection_method == "cash"
            else 0.0,
            "collection_method": self.collection_method,
            "transfer_amount": self.transfer_amount,
        }
        if stop.stop_type == "delivery" and self.office_credit:
            short = stop._earlydryer_short_amount(
                vals["cash_collected"], self.transfer_amount or 0.0
            )
            if short > 0:
                job = stop.job_id.with_env(self.env)
                if job._earlydryer_approval_rule("credit", short):
                    # as the office user: raises unless they may approve it
                    job._earlydryer_approval_ensure("credit", short)
                elif not self.env.user.has_group(
                    "earlydryer_base.group_branch_manager"
                ):
                    raise UserError(
                        self.env._("Only a Branch Manager approves credit.")
                    )
                job.sudo().message_post(
                    body=self.env._(
                        "%(amount)s left on credit on %(stop)s, approved by %(user)s.",
                        amount=stop._earlydryer_format(short),
                        stop=stop.name,
                        user=self.env.user.name,
                    ),
                    subtype_xmlid="mail.mt_note",
                )
                vals["office_approved"] = True
        stop._earlydryer_complete(vals)
        return True
