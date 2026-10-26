# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.http import request

# wrong badges / PINs allowed per tablet session before the lock
MAX_FAILURES = 5
LOCK_SECONDS = 120


class EarlydryerTabletIdentification(models.Model):
    """One row per identification attempt on a production tablet.

    The code or PIN typed is never stored. A successful row carries the
    token the tablet sends with each move: the server refuses it once the
    tablet was idle longer than the plant's ``tablet_idle_seconds``.
    """

    _name = "earlydryer.tablet.identification"
    _description = "Earlydryer Tablet Identification"
    _order = "date desc, id desc"
    _rec_name = "employee_id"

    date = fields.Datetime(
        required=True, index=True, default=fields.Datetime.now, readonly=True
    )
    user_id = fields.Many2one(
        "res.users",
        string="Tablet User",
        required=True,
        index=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    session_key = fields.Char(
        index=True,
        readonly=True,
        groups="base.group_system",
        help="Hash of the tablet's browser session.",
    )
    earlydryer_branch_id = fields.Many2one(
        "earlydryer.branch", string="Branch", required=True, index=True, readonly=True
    )
    employee_id = fields.Many2one("hr.employee", readonly=True)
    method = fields.Selection([("badge", "Badge"), ("pin", "PIN")], readonly=True)
    result = fields.Selection(
        [("ok", "Identified"), ("failed", "Wrong Code"), ("locked", "Locked")],
        required=True,
        readonly=True,
    )
    token = fields.Char(readonly=True, groups="base.group_system", copy=False)
    last_activity = fields.Datetime(readonly=True)
    ended = fields.Boolean(
        readonly=True, help="The tablet released or timed out this identification."
    )

    @api.model
    def _earlydryer_session_key(self):
        """Server-side key of the tablet's session (the client cannot reset it)."""
        sid = request.session.sid if request and request.session else None
        raw = sid or f"user-{self.env.uid}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @api.model
    def _earlydryer_is_locked(self, session_key, now=None):
        now = now or fields.Datetime.now()
        Ident = self.sudo()
        last_ok = Ident.search(
            [("session_key", "=", session_key), ("result", "=", "ok")],
            order="date desc, id desc",
            limit=1,
        )
        domain = [
            ("session_key", "=", session_key),
            ("result", "=", "failed"),
            ("date", ">=", now - timedelta(seconds=LOCK_SECONDS)),
        ]
        if last_ok:
            domain.append(("id", ">", last_ok.id))
        return Ident.search_count(domain) >= MAX_FAILURES

    @api.model
    def _earlydryer_log(self, branch, result, session_key, **vals):
        return self.sudo().create(
            {
                "earlydryer_branch_id": branch.id,
                "result": result,
                "session_key": session_key,
                "user_id": self.env.uid,
                **vals,
            }
        )

    @api.model
    def _earlydryer_check_token(self, token, branch):
        """Employee identified on this tablet by ``token``; refreshes the idle
        timer. Raises when unknown, of another user or plant, or timed out."""
        if not token:
            raise UserError(self.env._("Scan your badge or type your PIN first."))
        ident = self.sudo().search(
            [
                ("token", "=", token),
                ("result", "=", "ok"),
                ("user_id", "=", self.env.uid),
                ("earlydryer_branch_id", "=", branch.id),
            ],
            limit=1,
        )
        now = fields.Datetime.now()
        idle = timedelta(seconds=max(branch.tablet_idle_seconds, 10))
        if not ident or ident.ended or not ident.last_activity:
            raise UserError(self.env._("Scan your badge or type your PIN first."))
        if now - ident.last_activity > idle:
            ident.ended = True
            raise UserError(
                self.env._(
                    "The tablet was idle: scan your badge or type your PIN again."
                )
            )
        ident.last_activity = now
        return ident.employee_id.with_env(self.env)

    @api.model
    def _earlydryer_release(self, token):
        if token:
            self.sudo().search(
                [("token", "=", token), ("user_id", "=", self.env.uid)]
            ).ended = True
        return True

    @api.model
    def _earlydryer_new_token(self):
        return secrets.token_urlsafe(24)
