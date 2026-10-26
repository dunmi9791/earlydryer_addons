# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

# Colour group proposed for the items of each shipped service type. Set once
# at install (not as XML data) so Earlydryer's own changes survive module
# updates. Placeholders until Earlydryer confirms its sorting (see README).
SERVICE_TYPE_COLOUR_GROUPS = {
    "earlydryer_service_catalog.service_type_dry_cleaning": "special",
    "earlydryer_service_catalog.service_type_shoe_cleaning": "special",
    "earlydryer_service_catalog.service_type_bag_cleaning": "special",
    "earlydryer_service_catalog.service_type_rug_cleaning": "special",
}


def set_service_colour_groups(env):
    for xmlid, group in SERVICE_TYPE_COLOUR_GROUPS.items():
        service = env.ref(xmlid, raise_if_not_found=False)
        if service and not service.default_colour_group:
            service.default_colour_group = group
            # items created before the default existed
            env["laundry.job.item"].sudo().search(
                [("service_type_id", "=", service.id), ("colour_group", "=", False)]
            ).colour_group = group


def post_init_hook(env):
    set_service_colour_groups(env)
    Branch = env["earlydryer.branch"].with_context(active_test=False)
    branches = Branch.search([])  # pylint: disable=no-search-all
    branches._earlydryer_wash_batch_ensure_sequence()
