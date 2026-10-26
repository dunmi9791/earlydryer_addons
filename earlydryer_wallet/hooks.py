# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

AUDITLOG_RULE_XMLIDS = ("earlydryer_wallet.auditlog_rule_wallet_transaction",)


def _company_auditlog_rule(env):
    """Audit writes on res.company, where the wallet settings live.

    auditlog allows one rule per model: reuse the existing company rule
    (switching on its write log) or create one.
    """
    Rule = env["auditlog.rule"]
    model = env.ref("base.model_res_company")
    rule = Rule.with_context(active_test=False).search(
        [("model_id", "=", model.id)], limit=1
    )
    if not rule:
        rule = Rule.create(
            {
                "name": "Company (wallet settings)",
                "model_id": model.id,
                "log_type": "full",
                "log_create": False,
                "log_write": True,
                "log_unlink": False,
                "log_read": False,
                "log_export_data": False,
                "capture_record": False,
            }
        )
        env["ir.model.data"].create(
            {
                "module": "earlydryer_wallet",
                "name": "auditlog_rule_company_wallet_settings",
                "model": "auditlog.rule",
                "res_id": rule.id,
                "noupdate": True,
            }
        )
    elif not rule.log_write:
        if rule.state == "confirmed":
            rule.set_to_draft()
        rule.log_write = True
    return rule


def post_init_hook(env):
    """Accounts, journal and POS payment method of every company with a chart,
    then confirm the auditlog rules (see earlydryer_base)."""
    companies = env["res.company"].search([("chart_template", "!=", False)])
    companies._earlydryer_wallet_setup()
    rules = _company_auditlog_rule(env)
    for xmlid in AUDITLOG_RULE_XMLIDS:
        rules |= env.ref(xmlid, raise_if_not_found=False) or rules.browse()
    rules.filtered(lambda rule: rule.state == "draft").set_to_confirmed()
