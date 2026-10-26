# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json

from odoo import api, fields, models


class NotifyAlert(models.Model):
    _name = "earlydryer.notify.alert"
    _description = "Notification Alert Occurrence"
    rule_id = fields.Many2one(
        "earlydryer.notify.alert.rule", required=True, ondelete="cascade"
    )
    earlydryer_branch_id = fields.Many2one("earlydryer.branch")
    res_model = fields.Char(required=True)
    res_id = fields.Many2oneReference(model_field="res_model", required=True)
    occurrence = fields.Char(required=True)
    context_json = fields.Text(default="{}")
    done = fields.Boolean()
    _occurrence_unique = models.Constraint(
        "unique(rule_id,res_model,res_id,occurrence)",
        "Alert occurrence already registered.",
    )

    @api.model
    def _record_occurrence(self, rule, record, branch, context, occurrence):
        self.env["earlydryer.notify.message"]._lock(
            f"alert:{rule.id}:{record._name}:{record.id}:{occurrence}"
        )
        domain = [
            ("rule_id", "=", rule.id),
            ("res_model", "=", record._name),
            ("res_id", "=", record.id),
            ("occurrence", "=", occurrence),
        ]
        if self.search_count(domain):
            return self.browse()
        return self.create(
            {
                "rule_id": rule.id,
                "res_model": record._name,
                "res_id": record.id,
                "occurrence": occurrence,
                "earlydryer_branch_id": branch.id,
                "context_json": json.dumps(context),
            }
        )

    def _deliver(self):
        self.ensure_one()
        self = self.sudo()
        self.env.cr.execute(
            "SELECT id FROM earlydryer_notify_alert WHERE id=%s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset()
        if self.done:
            return
        record = self.env[self.res_model].browse(self.res_id).exists()
        if record:
            self.rule_id._deliver_to_recipients(
                record, self.earlydryer_branch_id, json.loads(self.context_json)
            )
        self.done = True
