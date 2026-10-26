# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools.misc import clean_context

from ..models.earlydryer_branch import BOARD_SUBCHANNEL, MACHINES_NOTIFICATION


class EarlydryerBreakdownWizard(models.TransientModel):
    """Report a machine breakdown in two taps: a corrective request for the
    machine's maintenance team, in the standard Maintenance app."""

    _name = "earlydryer.breakdown.wizard"
    _description = "Earlydryer Report Breakdown"

    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch",
        string="Branch",
        default=lambda self: self.env.user.sudo().earlydryer_branch_id,
    )
    equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Machine",
        required=True,
        domain="[('earlydryer_branch_id', '=', earlydryer_branch_id)]",
    )
    description = fields.Text(string="What happened?", required=True)
    photo = fields.Image(max_width=1280, max_height=1280)
    employee_id = fields.Many2one(
        "hr.employee",
        string="Reported By",
        domain="[('earlydryer_branch_id', 'in', [earlydryer_branch_id, False])]",
    )

    @api.model
    def _earlydryer_check_right(self):
        if not self.env["laundry.job"]._earlydryer_production_rights()["breakdown"]:
            raise AccessError(self.env._("You are not allowed to report breakdowns."))

    @api.model
    def _earlydryer_open(self, equipment=None, branch=None, employee_id=False):
        self._earlydryer_check_right()
        equipment = equipment or self.env["maintenance.equipment"]
        branch = branch or equipment.earlydryer_branch_id
        employee = (
            employee_id or self.env["laundry.job"]._earlydryer_default_employee().id
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Report Breakdown"),
            "res_model": self._name,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_earlydryer_branch_id": branch.id or False,
                "default_equipment_id": equipment.id or False,
                "default_employee_id": employee or False,
            },
        }

    def _earlydryer_create_request(self):
        self.ensure_one()
        self._earlydryer_check_right()
        equipment = self.equipment_id
        equipment.check_access("read")
        reporter = self.employee_id.sudo().name or self.env.user.name
        vals = {
            "name": self.env._("Breakdown: %(machine)s", machine=equipment.name),
            "equipment_id": equipment.id,
            "maintenance_type": "corrective",
            "priority": "3",
            "company_id": equipment.company_id.id or self.env.company.id,
            "description": Markup("<p>%s</p><p><i>%s</i></p>")
            % (
                self.description,
                self.env._(
                    "Reported from the plant by %(employee)s (%(user)s).",
                    employee=reporter,
                    user=self.env.user.name,
                ),
            ),
        }
        if equipment.maintenance_team_id:
            vals["maintenance_team_id"] = equipment.maintenance_team_id.id
        # sudo: hr_maintenance (auto-installed with hr + maintenance) computes
        # the owner from the equipment's employee, so the core "own requests"
        # rule may not let the reporter create it. The reporter follows it.
        # clean_context: a new context on purpose, so the wizard's default_*
        # keys do not reach the request (as core does).
        context = clean_context(self.env.context)
        Request = self.env["maintenance.request"].sudo()
        request = Request.with_context(context).create(vals)  # pylint: disable=context-overridden
        request.message_subscribe(partner_ids=self.env.user.partner_id.ids)
        request = request.with_env(self.env)
        if self.photo:
            attachment = (
                self.env["ir.attachment"]
                .sudo()
                .create(
                    {
                        "name": self.env._(
                            "Breakdown %(machine)s.jpg", machine=equipment.name
                        ),
                        "datas": self.photo,
                        "res_model": request._name,
                        "res_id": request.id,
                    }
                )
            )
            request.sudo().message_post(
                body=self.env._("Photo of the breakdown."),
                attachment_ids=attachment.ids,
                subtype_xmlid="mail.mt_note",
            )
        if equipment.earlydryer_branch_id:
            equipment.earlydryer_branch_id._bus_send(
                MACHINES_NOTIFICATION,
                {"branch_id": equipment.earlydryer_branch_id.id},
                subchannel=BOARD_SUBCHANNEL,
            )
        return request

    def action_confirm(self):
        request = self._earlydryer_create_request()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "warning",
                "message": self.env._(
                    "Breakdown reported: %(request)s. The machine shows as down "
                    "until the request is done.",
                    request=request.name,
                ),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
