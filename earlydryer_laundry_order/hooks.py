# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

AUDITLOG_RULE_XMLIDS = (
    "earlydryer_laundry_order.auditlog_rule_laundry_job",
    "earlydryer_laundry_order.auditlog_rule_laundry_job_item",
)

# Production stages each shipped service type does NOT go through. Set once at
# install (not as XML data) so later changes made by Earlydryer are kept on
# module updates. Placeholders until Earlydryer confirms (see README).
SERVICE_TYPE_SKIPS = {
    "earlydryer_service_catalog.service_type_ironing_only": ("uses_wash", "uses_dry"),
    "earlydryer_service_catalog.service_type_shoe_cleaning": ("uses_iron",),
    "earlydryer_service_catalog.service_type_bag_cleaning": ("uses_iron",),
    "earlydryer_service_catalog.service_type_rug_cleaning": ("uses_iron",),
    "earlydryer_service_catalog.service_type_wash_fold": ("uses_iron",),
}


def _confirm_auditlog_rules(env):
    """auditlog 19.0 only logs rules in state ``confirmed`` (see earlydryer_base)."""
    rules = env["auditlog.rule"]
    for xmlid in AUDITLOG_RULE_XMLIDS:
        rules |= env.ref(xmlid, raise_if_not_found=False) or rules.browse()
    rules.filtered(lambda rule: rule.state == "draft").set_to_confirmed()


def _set_service_type_skips(env):
    for xmlid, fnames in SERVICE_TYPE_SKIPS.items():
        service = env.ref(xmlid, raise_if_not_found=False)
        if service:
            service.write(dict.fromkeys(fnames, False))


def post_init_hook(env):
    # sequences of the branches that existed before this module
    Branch = env["earlydryer.branch"].with_context(active_test=False)
    branches = Branch.search([])  # pylint: disable=no-search-all
    branches._laundry_job_ensure_sequence()
    _set_service_type_skips(env)
    _confirm_auditlog_rules(env)
