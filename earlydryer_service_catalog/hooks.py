# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

AUDITLOG_RULE_XMLIDS = (
    "earlydryer_service_catalog.auditlog_rule_product_pricelist_item",
    "earlydryer_service_catalog.auditlog_rule_earlydryer_surcharge",
    "earlydryer_service_catalog.auditlog_rule_earlydryer_service_type",
)


def _enable_pricelists(env):
    """Turn on Settings > Sales > Pricelists, like ``res.config.settings``.

    ``product.res_config_settings.group_product_pricelist`` is an
    ``implied_group`` field on ``base.group_user``: saving the setting calls
    ``_apply_group`` on the internal user group and then
    ``res.company._activate_or_create_pricelists()``. Do the same here instead
    of saving a whole settings record (which would write every other setting).
    """
    user_group = env.ref("base.group_user")
    pricelist_group = env.ref("product.group_product_pricelist")
    if pricelist_group not in user_group.all_implied_ids:
        user_group._apply_group(pricelist_group)
        env["res.company"]._activate_or_create_pricelists()


def _confirm_auditlog_rules(env):
    """auditlog 19.0 only logs rules in state ``confirmed`` (see earlydryer_base)."""
    rules = env["auditlog.rule"]
    for xmlid in AUDITLOG_RULE_XMLIDS:
        rules |= env.ref(xmlid, raise_if_not_found=False) or rules.browse()
    rules.filtered(lambda rule: rule.state == "draft").set_to_confirmed()


def post_init_hook(env):
    _enable_pricelists(env)
    _confirm_auditlog_rules(env)
