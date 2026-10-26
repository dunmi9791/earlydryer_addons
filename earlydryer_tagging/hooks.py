# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).


def post_init_hook(env):
    """Tag settings of the branches that existed before this module."""
    Branch = env["earlydryer.branch"].with_context(active_test=False)
    branches = Branch.search([])  # pylint: disable=no-search-all
    branches._earlydryer_tag_ensure_setup()
