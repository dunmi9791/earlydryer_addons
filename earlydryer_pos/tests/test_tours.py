# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import importlib.util

from odoo.tests import HttpCase, tagged

from .common import EarlydryerPosCommon


@tagged("post_install", "-at_install")
class TestPosTours(EarlydryerPosCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_front_desk.write({"password": "t_front_desk_pw"})

    def setUp(self):
        super().setUp()
        if not importlib.util.find_spec("websocket"):
            # the official odoo:19 image ships neither Chrome nor websocket-client
            self.skipTest("POS tours need Chrome and websocket-client.")

    def _tour(self, name):
        self.config.with_user(self.user_front_desk).open_ui()
        self.start_tour(f"/pos/ui/{self.config.id}", name, login="t_front_desk")

    def test_intake_tour(self):
        self._tour("earlydryer_pos_intake")
        order = self.Order.search(
            [("config_id", "=", self.config.id)], limit=1, order="id desc"
        )
        self.assertTrue(order.earlydryer_job_id)
        self.assertEqual(order.earlydryer_job_id.amount_due, order.amount_total - 1000)

    def test_walk_in_refused_tour(self):
        self._tour("earlydryer_pos_walk_in_refused")

    def test_discount_pin_tour(self):
        self._tour("earlydryer_pos_discount_pin")

    def test_collection_tour(self):
        session = self._open_session()
        order = self._sync(self._payload([self._line(self.shirt_wi)]))
        self._make_ready(order.earlydryer_job_id)
        self.assertTrue(session)
        self._tour("earlydryer_pos_collection")

    def test_offline_intake_tour(self):
        self._tour("earlydryer_pos_offline_intake")
