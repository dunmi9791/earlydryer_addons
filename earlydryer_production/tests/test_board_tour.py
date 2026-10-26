# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import importlib.util

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestBoardTour(HttpCase):
    def test_stage_board_tour(self):
        if not importlib.util.find_spec("websocket"):
            # the official odoo:19 image ships neither Chrome nor websocket-client
            self.skipTest("Browser tours need Chrome and websocket-client.")
        self.env.ref("base.user_admin").write(
            {
                "earlydryer_branch_ids": [
                    (4, self.env.ref("earlydryer_base.branch_plant_1").id)
                ],
                "earlydryer_branch_id": self.env.ref(
                    "earlydryer_base.branch_plant_1"
                ).id,
            }
        )
        self.start_tour(
            "/odoo/action-earlydryer_production.action_earlydryer_stage_board",
            "earlydryer_production_stage_board",
            login="admin",
        )
