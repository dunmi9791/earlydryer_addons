# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

AUDITLOG_RULE_XMLIDS = (
    "earlydryer_base.auditlog_rule_earlydryer_branch",
    "earlydryer_base.auditlog_rule_earlydryer_approval_rule",
    "earlydryer_base.auditlog_rule_earlydryer_approval_request",
)


def post_init_hook(env):
    """Subscribe the auditlog rules shipped with this module.

    auditlog 19.0 only patches models for rules in state ``confirmed`` and
    creates the "View logs" action in ``set_to_confirmed()``, so the rules
    loaded from XML (state ``draft``) must be confirmed explicitly.
    """
    rules = env["auditlog.rule"]
    for xmlid in AUDITLOG_RULE_XMLIDS:
        rules |= env.ref(xmlid, raise_if_not_found=False) or rules.browse()
    rules.filtered(lambda rule: rule.state == "draft").set_to_confirmed()
