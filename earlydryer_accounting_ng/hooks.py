# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

AUDITLOG_RULE_XMLIDS = (
    "earlydryer_accounting_ng.auditlog_rule_account_tax",
    "earlydryer_accounting_ng.auditlog_rule_wht_category",
    "earlydryer_accounting_ng.auditlog_rule_account_account",
)


def _ensure_auditlog_rule(env, model_xmlid, name, xmlid):
    """auditlog allows one rule per model: reuse an existing rule of the model
    (switching on create and write logs) or create one."""
    Rule = env["auditlog.rule"].with_context(active_test=False)
    model = env.ref(model_xmlid)
    rule = Rule.search([("model_id", "=", model.id)], limit=1)
    if not rule:
        rule = Rule.create(
            {
                "name": name,
                "model_id": model.id,
                "log_type": "full",
                "log_create": True,
                "log_write": True,
                "log_unlink": True,
                "log_read": False,
                "log_export_data": False,
                "capture_record": True,
            }
        )
        env["ir.model.data"].create(
            {
                "module": "earlydryer_accounting_ng",
                "name": xmlid,
                "model": "auditlog.rule",
                "res_id": rule.id,
                "noupdate": True,
            }
        )
    elif not (rule.log_create and rule.log_write):
        if rule.state == "confirmed":
            rule.set_to_draft()
        rule.write({"log_create": True, "log_write": True})
    return rule


def post_init_hook(env):
    """Audit taxes, WHT categories, accounts and the company tax settings
    (res.company write, shared with earlydryer_wallet), then confirm the rules
    (see earlydryer_base)."""
    rules = env["auditlog.rule"]
    for model_xmlid, name, xmlid in (
        ("account.model_account_tax", "Taxes", "auditlog_rule_account_tax"),
        ("account.model_account_account", "Accounts", "auditlog_rule_account_account"),
        (
            "earlydryer_accounting_ng.model_earlydryer_wht_category",
            "WHT categories",
            "auditlog_rule_wht_category",
        ),
    ):
        rules |= _ensure_auditlog_rule(env, model_xmlid, name, xmlid)
    company_rule = (
        env["auditlog.rule"]
        .with_context(active_test=False)
        .search([("model_id", "=", env.ref("base.model_res_company").id)], limit=1)
    )
    if company_rule and not company_rule.log_write:
        if company_rule.state == "confirmed":
            company_rule.set_to_draft()
        company_rule.log_write = True
    rules |= company_rule
    rules.filtered(lambda rule: rule.state == "draft").set_to_confirmed()
