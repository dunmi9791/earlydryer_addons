# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).


def post_init_hook(env):
    for xmlid in ("audit_provider", "audit_template", "audit_alert_rule"):
        rule = env.ref("earlydryer_notifications." + xmlid)
        if rule.state == "draft":
            rule.set_to_confirmed()
