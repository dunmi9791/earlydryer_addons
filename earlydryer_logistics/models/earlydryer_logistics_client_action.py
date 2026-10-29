# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json

from odoo import api, fields, models


class EarlydryerLogisticsClientAction(models.Model):
    """One row per action sent by the rider phone (client-generated UUID).

    The rider view queues actions offline and may send one twice (lost
    answer, retry): the stored result is returned instead of acting again.
    """

    _name = "earlydryer.logistics.client.action"
    _description = "Earlydryer Rider Action (idempotency)"
    _order = "id desc"
    _rec_name = "uuid"

    uuid = fields.Char(required=True, index=True, readonly=True)
    action = fields.Char(required=True, readonly=True)
    stop_id = fields.Many2one(
        "earlydryer.logistics.stop", readonly=True, ondelete="cascade", index=True
    )
    trip_id = fields.Many2one(
        "earlydryer.logistics.trip", readonly=True, ondelete="cascade", index=True
    )
    user_id = fields.Many2one(
        "res.users", readonly=True, default=lambda self: self.env.user
    )
    result_json = fields.Text(readonly=True)

    _uuid_uniq = models.Constraint(
        "unique(uuid)", "A rider action is recorded once per client id."
    )

    @api.model
    def _earlydryer_get(self, uuid):
        if not uuid:
            return self.browse()
        return self.sudo().search([("uuid", "=", uuid)], limit=1)

    @api.model
    def _earlydryer_run(self, uuid, action, func, stop=None, trip=None):
        """Run ``func()`` once per ``uuid``; returns its (stored) result."""
        existing = self._earlydryer_get(uuid)
        if existing:
            result = json.loads(existing.result_json or "{}")
            result["duplicate"] = True
            return result
        # serialise concurrent retries of the same uuid
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", [f"edlog:{uuid}"]
        )
        existing = self._earlydryer_get(uuid)
        if existing:
            result = json.loads(existing.result_json or "{}")
            result["duplicate"] = True
            return result
        result = func()
        if uuid:
            self.sudo().create(
                {
                    "uuid": uuid,
                    "action": action,
                    "stop_id": stop.id if stop else False,
                    "trip_id": trip.id if trip else False,
                    "result_json": json.dumps(result, default=str),
                }
            )
        return result
