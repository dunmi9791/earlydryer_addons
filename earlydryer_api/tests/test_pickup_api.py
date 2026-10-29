# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged
from odoo.tools.misc import mute_logger

from odoo.addons.earlydryer_logistics.tests.common import LogisticsCommon
from odoo.addons.fastapi.dependencies import fastapi_endpoint_id
from odoo.addons.fastapi.tests.common import FastAPITransactionCase

from ..routers import pickup_router


@tagged("post_install", "-at_install")
class TestPickupApi(LogisticsCommon, FastAPITransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.endpoint = cls.env.ref("earlydryer_api.endpoint_api")
        cls.endpoint.earlydryer_api_key = "t-secret-key"
        cls.default_fastapi_router = pickup_router
        cls.default_fastapi_running_user = cls.env.ref("earlydryer_api.user_api")
        cls.default_fastapi_dependency_overrides = {
            fastapi_endpoint_id: lambda: cls.endpoint.id
        }
        cls.headers = {"X-Api-Key": "t-secret-key"}

    def _client(self):
        return self._create_test_client(raise_server_exceptions=False)

    def _pickup(self, **vals):
        return {
            "name": "T App Customer",
            "phone": "0809 222 3344",
            "area_id": self.area_near.id,
            "street": "3 T Close",
            "slot_key": self._first_slot_key("pickup"),
            **vals,
        }

    def test_api_key_required(self):
        with self._client() as client:
            self.assertEqual(client.get("/areas").status_code, 401)
            response = client.get("/areas", headers={"X-Api-Key": "wrong"})
            self.assertEqual(response.status_code, 401)
        self.endpoint.earlydryer_api_key = False
        with self._client() as client:
            response = client.get("/areas", headers={"X-Api-Key": ""})
            self.assertEqual(response.status_code, 401)

    def test_areas_and_quote(self):
        with self._client() as client:
            areas = client.get("/areas", headers=self.headers).json()
            self.assertIn(self.area_near.id, [area["id"] for area in areas])
            response = client.post(
                "/pickups/quote",
                headers=self.headers,
                json={"area_id": self.area_near.id, "date": str(self.tomorrow)},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["served"])
        self.assertTrue(response.json()["slots"])

    def test_book_track_cancel(self):
        with self._client() as client:
            response = client.post(
                "/pickups",
                headers=self.headers,
                json=self._pickup(client_ref="t-app-1", fee=0),
            )
            self.assertEqual(response.status_code, 201, response.text)
            pickup = response.json()
            stop = self.Stop.search([("name", "=", pickup["reference"])])
            self.assertEqual(stop.source, "app")
            self.assertEqual(stop.state, "scheduled")
            # the reference contains slashes (P1/STP/00001)
            path = f"/pickups/{pickup['reference']}"
            params = {"token": pickup["access_token"]}
            response = client.get(path, headers=self.headers, params=params)
            self.assertEqual(response.json()["reference"], pickup["reference"])
            response = client.get(
                path, headers=self.headers, params={"token": "wrong"}
            )
            self.assertEqual(response.status_code, 400)
            response = client.post(
                f"{path}/cancel", headers=self.headers, params=params
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["state"], "cancelled")

    @mute_logger("odoo.addons.fastapi.error_handlers")
    def test_errors(self):
        with self._client() as client:
            response = client.post(
                "/pickups",
                headers=self.headers,
                json=self._pickup(area_id=self.area_unserved.id),
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("T Nowhere", response.json()["detail"])
            response = client.post(
                "/pickups", headers=self.headers, json={"phone": "x"}
            )
            self.assertEqual(response.status_code, 422)

    def test_callback(self):
        with self._client() as client:
            response = client.post(
                "/pickups/callback",
                headers=self.headers,
                json={
                    "name": "T Far Away",
                    "phone": "0809 333 4455",
                    "area_id": self.area_unserved.id,
                    "street": "9 T Lane",
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["state"], "draft")
