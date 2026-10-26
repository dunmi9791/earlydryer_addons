# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

AUDITLOG_RULE_XMLIDS = ("earlydryer_pos.auditlog_rule_pos_order_line",)


def post_init_hook(env):
    """Confirm the shipped auditlog rules (auditlog 19.0 only logs confirmed
    rules, see earlydryer_base)."""
    rules = env["auditlog.rule"]
    for xmlid in AUDITLOG_RULE_XMLIDS:
        rules |= env.ref(xmlid, raise_if_not_found=False) or rules.browse()
    rules.filtered(lambda rule: rule.state == "draft").set_to_confirmed()
