# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from .tools import has_any


def post_init_hook(env):
    action = env.ref("earlydryer_reporting.action_dashboard")
    for user in (
        env["res.users"]
        .sudo()
        .search([("share", "=", False), ("action_id", "=", False)])
    ):
        if has_any(env(user=user), ("group_management", "group_operations_manager")):
            user.action_id = action.id
    env["earlydryer.report.subscription"]._defaults()
