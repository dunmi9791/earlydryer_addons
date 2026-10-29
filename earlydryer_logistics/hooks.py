# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

AUDIT_RULES = ("auditlog_rule_zone", "auditlog_rule_stop", "auditlog_rule_trip")


def post_init_hook(env):
    # OCA auditlog 19 only logs rules in state "confirmed"
    for xmlid in AUDIT_RULES:
        rule = env.ref(f"earlydryer_logistics.{xmlid}", raise_if_not_found=False)
        if rule and rule.state == "draft":
            rule.set_to_confirmed()
    env["earlydryer.branch"].search([])._earlydryer_logistics_ensure_sequences()
