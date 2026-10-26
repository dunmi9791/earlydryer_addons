# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain

from .earlydryer_tablet_identification import LOCK_SECONDS

BADGE_REPORT = "earlydryer_production.action_report_employee_badge"


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model
    def _earlydryer_identify(self, code_or_pin, branch_id, session_key=None):
        """Employee of plant ``branch_id`` whose badge or PIN is ``code_or_pin``.

        Only employees of that plant, or without a plant, match. Wrong codes
        are logged and rate-limited per tablet session: after
        ``MAX_FAILURES`` failures within ``LOCK_SECONDS`` the session is
        locked for that time.

        :returns: ``(employee, identification)``; the identification row
            carries the token the tablet sends with its moves
        :raises UserError: unknown code, ambiguous PIN or locked session
        """
        Ident = self.env["earlydryer.tablet.identification"]
        branch = self.env["earlydryer.branch"].browse(branch_id).exists()
        if not branch or branch not in self.env.user._earlydryer_allowed_branches():
            raise AccessError(self.env._("You do not work on this plant."))
        if not branch._earlydryer_uses_tablet():
            raise UserError(
                self.env._(
                    "Plant %(branch)s does not use the production tablet.",
                    branch=branch.display_name,
                )
            )
        session_key = session_key or Ident._earlydryer_session_key()
        if Ident._earlydryer_is_locked(session_key):
            Ident._earlydryer_log(branch, "locked", session_key)
            raise UserError(
                self.env._(
                    "Too many wrong codes: the tablet is locked for %(minutes)s "
                    "minutes.",
                    minutes=LOCK_SECONDS // 60,
                )
            )
        code = (code_or_pin or "").strip()
        # badge and PIN are HR fields: read with sudo, match on this plant only
        Employee = self.sudo().with_context(active_test=True)
        scope = Domain("earlydryer_branch_id", "in", [branch.id, False])
        employee, method = Employee.browse(), False
        if code:
            employee = Employee.search(scope & Domain("barcode", "=", code), limit=1)
            method = "badge"
            if not employee and code.isdigit():
                employee = Employee.search(scope & Domain("pin", "=", code), limit=2)
                method = "pin"
                if len(employee) > 1:
                    raise UserError(
                        self.env._(
                            "This PIN is used by several people: scan your badge."
                        )
                    )
        if not employee:
            Ident._earlydryer_log(branch, "failed", session_key, method=method)
            raise UserError(self.env._("Unknown badge or PIN."))
        ident = Ident._earlydryer_log(
            branch,
            "ok",
            session_key,
            method=method,
            employee_id=employee.id,
            token=Ident._earlydryer_new_token(),
            last_activity=Ident._fields["date"].default(Ident),
        )
        return self.browse(employee.id), ident

    def action_print_earlydryer_badge(self):
        employees = self.sudo()
        missing = employees.filtered(lambda e: not e.barcode)
        if missing:
            if not self.env.user.has_group("hr.group_hr_user"):
                raise UserError(
                    self.env._(
                        "%(names)s has no badge ID yet: ask HR to generate one.",
                        names=", ".join(missing.mapped("name")),
                    )
                )
            missing.generate_random_barcode()
        # config=False: a badge needs no company document layout
        return self.env.ref(BADGE_REPORT).report_action(self, config=False)
